"""Run in local-check API container with disposable client cert/key under /tmp.

Pass LOCAL_CONTAINER_CHECK=yes and CMS_CHECK_PASSWORD from a private test env.
The matching synthetic account is created by cms-account.cjs on the CMS copy.
"""

import http.cookiejar
import json
import os
import ssl
import urllib.error
import urllib.request
import uuid

assert os.environ.get("LOCAL_CONTAINER_CHECK") == "yes"
context = ssl._create_unverified_context()
plain = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
)
for path in ("/admin", "/admin/login", "/content-manager/init", "/api/public-content/pages"):
    try:
        plain.open("https://proxy:9443" + path, timeout=10)
        raise AssertionError("CMS accepted a request without a client certificate")
    except urllib.error.HTTPError as response:
        assert response.status == 400
print("PASS: CMS admin/service/content routes require a client certificate")

context.load_cert_chain("/tmp/cms-client-cert.pem", "/tmp/cms-client-key.pem")
cookies = http.cookiejar.CookieJar()
client = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=context),
    urllib.request.HTTPCookieProcessor(cookies),
)


def request(path, payload=None, token=None):
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        "https://proxy:9443" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    with client.open(req, timeout=15) as response:
        assert response.status == 200
        body = response.read()
        return (
            json.loads(body)
            if "application/json" in response.headers.get("Content-Type", "")
            else body
        )


assert b"<!doctype html>" in request("/admin").lower()
device = str(uuid.uuid4())
response = request(
    "/admin/login",
    {
        "email": "vi0-cms@example.org",
        "password": os.environ["CMS_CHECK_PASSWORD"],
        "rememberMe": False,
        "deviceId": device,
    },
)
token = response["data"]["token"]
refresh = next(c for c in cookies if c.name == "strapi_admin_refresh")
assert refresh.secure and "httponly" in {key.lower() for key in refresh._rest}
request("/admin/users/me", token=token)
request("/admin/logout", {"deviceId": device}, token=token)
print("PASS: CMS admin assets, real login, Secure refresh cookie, Bearer API and logout over mTLS")
