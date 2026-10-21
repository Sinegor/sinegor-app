import { useState } from "react";
import { value, diskUrl, type Models } from "../../lib/admin/api";
import { date } from "../../lib/admin/labels";
import { Button, Card, Field, Form } from "../ui";
import { Check, formData, text, type Operation } from "./common";
export function FolderPanel({
  orderId,
  folder,
  op,
}: {
  orderId: string;
  folder: Models["FolderRead"] | null;
  op: Operation;
}) {
  const [url, setUrl] = useState<string | null>(null);
  return (
    <Card title="Папка на Яндекс Диске">
      <p>
        Материалы и результат передаются непосредственно на Диске. Права
        выдаются и меняются вручную.
      </p>
      {folder ? (
        <>
          <p className="break-word">Путь: {folder.disk_path}</p>
          <p>Удалена: {date(folder.deleted_at)}</p>
          {folder.deletion_started_at && !folder.deleted_at && (
            <p>
              Операция удаления начата. Состояние и проверка — в разделе
              удаления ниже.
            </p>
          )}
          {!folder.deleted_at && !folder.deletion_operation_id && (
            <>
              <Button
                disabled={op.busy}
                onClick={() =>
                  op.run(async (api) => {
                    const found = diskUrl(
                      await value(
                        api.GET("/api/admin/orders/{order_id}/folder/open", {
                          params: { path: { order_id: orderId } },
                        }),
                      ),
                    );
                    if (!found) throw new Error("Неверный адрес папки");
                    setUrl(found);
                  }, "Ссылка на папку получена.")
                }
              >
                Получить ссылку для открытия
              </Button>
              {url && (
                <p>
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    Открыть папку на Диске ↗
                  </a>
                </p>
              )}
            </>
          )}
          {!folder.deleted_at && !folder.deletion_started_at && (
            <>
              <Form
                method="post"
                busy={op.busy}
                onSubmit={(event) => {
                  const data = formData(event);
                  void op.run(
                    (api) =>
                      value(
                        api.PUT("/api/admin/orders/{order_id}/folder/link", {
                          params: { path: { order_id: orderId } },
                          body: {
                            folder_url: text(data, "folder_url"),
                            access_granted: true,
                          },
                        }),
                      ),
                    "Клиентская ссылка сохранена.",
                  );
                }}
              >
                <Field
                  label="Ссылка для заказчика"
                  name="folder_url"
                  type="url"
                  required
                  maxLength={2048}
                  defaultValue={folder.folder_url ?? ""}
                />
                <Check name="access_granted">
                  Я вручную предоставил заказчику доступ к этой папке
                </Check>
                <Button type="submit">Сохранить клиентскую ссылку</Button>
              </Form>
              {!folder.resource_id && (
                <p>
                  <Button
                    disabled={op.busy}
                    onClick={() =>
                      op.run(
                        (api) =>
                          value(
                            api.PUT("/api/admin/orders/{order_id}/folder", {
                              params: { path: { order_id: orderId } },
                              body: { disk_path: folder.disk_path },
                            }),
                          ),
                        "Идентичность папки проверена.",
                      )
                    }
                  >
                    Проверить существующую привязку
                  </Button>
                </p>
              )}
            </>
          )}
        </>
      ) : (
        <>
          <Button
            disabled={op.busy}
            onClick={() =>
              op.run(
                (api) =>
                  value(
                    api.POST("/api/admin/orders/{order_id}/folder", {
                      params: { path: { order_id: orderId } },
                    }),
                  ),
                "Папка создана и привязана.",
                "Если ответ потерян, сначала проверьте папку на Диске и привяжите её явно.",
              )
            }
          >
            Создать папку заказа
          </Button>
          <Form
            method="post"
            busy={op.busy}
            onSubmit={(event) => {
              const data = formData(event);
              void op.run(
                (api) =>
                  value(
                    api.PUT("/api/admin/orders/{order_id}/folder", {
                      params: { path: { order_id: orderId } },
                      body: { disk_path: text(data, "disk_path") },
                    }),
                  ),
                "Папка проверена и привязана.",
              );
            }}
          >
            <Field
              label="Путь существующей папки"
              name="disk_path"
              placeholder="disk:/SINEGOR/orders/..."
              required
              maxLength={1024}
            />
            <Check name="folder_checked">
              Я проверил принадлежность папки этому заказу
            </Check>
            <Button type="submit">Привязать существующую папку</Button>
          </Form>
        </>
      )}
    </Card>
  );
}
