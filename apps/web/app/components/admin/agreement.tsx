import { useState } from "react";
import {
  uploadInitial,
  downloadAgreement,
  savePdf,
  type Models,
} from "../../lib/admin/api";
import { agreements, date } from "../../lib/admin/labels";
import { Button, Card, Field, Form, Modal, Notice } from "../ui";
import { Check, formData, text, type Operation } from "./common";
export function AgreementPanel({
  order,
  agreement,
  op,
}: {
  order: Models["OrderRead"];
  agreement: Models["AgreementRead"] | null;
  op: Operation;
}) {
  const [reviewed, setReviewed] = useState<number | null>(null);
  const [decision, setDecision] = useState("approve");
  const [pending, setPending] = useState<{
    revision: number;
    reason: string;
    approve: boolean;
  } | null>(null);
  const editable = order.status === "awaiting_agreement";
  return (
    <Card title="Соглашение PDF">
      {agreement ? (
        <>
          <p>
            <span className={`badge ${agreement.status}`}>
              {agreements[agreement.status]}
            </span>{" "}
            Версия {agreement.revision}
          </p>
          {agreement.rejection_reason && (
            <Notice error>
              Причина отклонения: {agreement.rejection_reason}
            </Notice>
          )}
          {agreement.verified_at && (
            <p>Проверено: {date(agreement.verified_at)}</p>
          )}
          {agreement.final_sha256 && (
            <p className="break-word">SHA-256: {agreement.final_sha256}</p>
          )}
          <div className="actions">
            {(["initial", "returned", "final"] as const)
              .filter((kind) => agreement[`${kind}_available`])
              .map((kind) => (
                <Button
                  key={kind}
                  disabled={op.busy}
                  onClick={() =>
                    op.run(async (api) => {
                      const downloaded = await downloadAgreement(
                        api,
                        order.id,
                        kind,
                      );
                      savePdf(
                        downloaded.blob,
                        `order-${order.number}-${kind}-v${downloaded.revision}.pdf`,
                      );
                      if (kind === "returned") setReviewed(downloaded.revision);
                    }, "PDF скачан. Проверьте документ и подписи вне сайта.")
                  }
                >
                  {kind === "initial"
                    ? "Скачать PDF исполнителя"
                    : kind === "returned"
                      ? "Скачать PDF заказчика"
                      : "Скачать окончательный PDF"}
                </Button>
              ))}
          </div>
        </>
      ) : (
        <p>Соглашение ещё не загружено.</p>
      )}
      {editable &&
        (!agreement ||
          ["awaiting_customer", "rejected"].includes(agreement.status)) && (
          <Form
            method="post"
            busy={op.busy}
            onSubmit={(event) => {
              const data = formData(event),
                file = data.get("pdf");
              if (!(file instanceof File) || !file.size) {
                op.setNotice({
                  text: "Выберите непустой файл PDF.",
                  error: true,
                });
                return;
              }
              void op.run(
                (api) =>
                  uploadInitial(api, order.id, agreement?.revision ?? 0, file),
                "PDF исполнителя сохранён.",
              );
            }}
          >
            <p>
              Загружайте только соглашение, подписанное исполнителем. Материалы
              заказа передаются через Яндекс Диск.
            </p>
            <Field
              label="PDF исполнителя"
              type="file"
              name="pdf"
              accept="application/pdf,.pdf"
              required
            />
            <Button type="submit">
              {agreement
                ? "Заменить PDF исполнителя"
                : "Загрузить PDF исполнителя"}
            </Button>
          </Form>
        )}
      {editable && agreement?.status === "under_review" && (
        <>
          <p>
            Сначала скачайте и проверьте экземпляр заказчика. Решение относится
            к версии скачанного PDF.
          </p>
          <Form
            method="post"
            busy={op.busy || reviewed !== agreement.revision}
            onSubmit={(event) => {
              const data = formData(event);
              if (reviewed !== agreement.revision) return;
              const reason = decision === "reject" ? text(data, "reason") : "";
              if (decision === "reject" && !reason) {
                op.setNotice({
                  text: "Укажите причину отклонения.",
                  error: true,
                });
                return;
              }
              setPending({
                revision: reviewed,
                reason,
                approve: decision === "approve",
              });
            }}
          >
            <p>Скачанная версия: {reviewed ?? "не выбрана"}</p>
            <Check name="signatures_checked">
              Я проверил документ и подписи в скачанном PDF
            </Check>
            <label className="field">
              Решение
              <select
                name="decision"
                value={decision}
                onChange={(event) => setDecision(event.target.value)}
              >
                <option value="approve">Утвердить</option>
                <option value="reject">Отклонить</option>
              </select>
            </label>
            <label className="field">
              Причина отклонения
              <textarea
                name="reason"
                rows={3}
                maxLength={2000}
                required={decision === "reject"}
                disabled={decision !== "reject"}
                onChange={(event) =>
                  event.currentTarget.setCustomValidity(
                    event.currentTarget.value.trim()
                      ? ""
                      : "Укажите причину отклонения.",
                  )
                }
              />
            </label>
            <Button type="submit">Продолжить</Button>
          </Form>
        </>
      )}
      <Modal
        busy={op.busy}
        open={!!pending}
        title={
          pending?.approve ? "Утвердить соглашение?" : "Отклонить соглашение?"
        }
        onClose={() => {
          if (!op.busy) setPending(null);
        }}
      >
        {pending && op.notice?.error && <Notice error>{op.notice.text}</Notice>}
        <p>
          Заказ № {order.number}, версия PDF {pending?.revision}.{" "}
          {pending?.approve
            ? "Документ станет окончательным, заказ перейдёт в ожидание материалов."
            : "Заказчик увидит причину отклонения и сможет подписать документ повторно."}
        </p>
        {pending && (
          <Button
            disabled={op.busy}
            onClick={() => {
              const snapshot = pending;
              void op.run(
                async (api) => {
                  if (snapshot.approve)
                    await api.POST(
                      "/api/admin/orders/{order_id}/agreement/approve",
                      {
                        params: { path: { order_id: order.id } },
                        body: { revision: snapshot.revision },
                      },
                    );
                  else
                    await api.POST(
                      "/api/admin/orders/{order_id}/agreement/reject",
                      {
                        params: { path: { order_id: order.id } },
                        body: {
                          revision: snapshot.revision,
                          reason: snapshot.reason,
                        },
                      },
                    );
                  setPending(null);
                },
                snapshot.approve
                  ? "Соглашение утверждено."
                  : "Соглашение отклонено.",
              );
            }}
          >
            {pending.approve ? "Утвердить версию" : "Отклонить версию"}
          </Button>
        )}
      </Modal>
    </Card>
  );
}
