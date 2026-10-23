import {
  uploadReturned,
  downloadCustomerAgreement,
  savePdf,
  type Models,
} from "../../lib/customer/api";
import { agreements, date } from "../../lib/admin/labels";
import type { Operation } from "../admin/common";
import { Check, formData } from "./common";
import { Button, Card, Field, Form, Notice } from "../ui";
export function CustomerAgreement({
  order,
  agreement,
  op,
}: {
  order: Models["OrderRead"];
  agreement: Models["AgreementRead"] | null;
  op: Operation;
}) {
  if (!agreement)
    return (
      <Card title="Соглашение">
        <p>
          Исполнитель ещё не разместил соглашение. Оно появится в этой карточке.
        </p>
      </Card>
    );
  const canUpload =
    order.status === "awaiting_agreement" &&
    agreement.initial_available &&
    ["awaiting_customer", "under_review", "rejected"].includes(
      agreement.status,
    );
  return (
    <Card title="Соглашение">
      <p>
        <span className={`badge ${agreement.status}`}>
          {agreements[agreement.status]}
        </span>{" "}
        Версия документа {agreement.revision}
      </p>
      {agreement.rejection_reason && (
        <Notice error>
          Исполнитель отклонил документ: {agreement.rejection_reason}
        </Notice>
      )}
      {agreement.status === "approved" && (
        <p>
          Соглашение утверждено {date(agreement.verified_at)}. Подписанный
          экземпляр сохраняется отдельно от материалов заказа.
        </p>
      )}
      {agreement.status === "under_review" && (
        <p>Ваш PDF получен и ожидает проверки исполнителем.</p>
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
                  const downloaded = await downloadCustomerAgreement(
                    api,
                    order.id,
                    kind,
                  );
                  savePdf(
                    downloaded.blob,
                    `order-${order.number}-${kind}-v${downloaded.revision}.pdf`,
                  );
                }, "Соглашение подготовлено к скачиванию.")
              }
            >
              {kind === "initial"
                ? "Скачать соглашение исполнителя"
                : kind === "returned"
                  ? "Скачать отправленный PDF"
                  : "Скачать подписанное соглашение"}
            </Button>
          ))}
      </div>
      {canUpload && (
        <Form
          method="post"
          busy={op.busy}
          onSubmit={(event) => {
            const data = formData(event),
              file = data.get("signed_pdf");
            if (!(file instanceof File) || !file.size) {
              op.setNotice({
                text: "Выберите непустой файл PDF.",
                error: true,
              });
              return;
            }
            void op.run(
              (api) => uploadReturned(api, order.id, agreement.revision, file),
              "Подписанный PDF отправлен исполнителю на проверку.",
            );
          }}
        >
          <p>
            Скачайте соглашение исполнителя, подпишите его и отправьте
            подписанный экземпляр PDF. Исполнитель проверит документ вручную.
          </p>
          {agreement.status === "under_review" && (
            <p>До решения исполнителя можно заменить отправленный экземпляр.</p>
          )}
          <Field
            label="Подписанное соглашение PDF"
            type="file"
            name="signed_pdf"
            accept="application/pdf,.pdf"
            required
          />
          <Check name="signed">Отправляю соглашение с моей подписью</Check>
          <Button type="submit">
            {agreement.status === "under_review"
              ? "Заменить отправленный PDF"
              : "Отправить подписанный PDF"}
          </Button>
          <p className="muted">
            Здесь отправляется только соглашение. Исходные документы передавайте
            через папку на Яндекс Диске.
          </p>
        </Form>
      )}
    </Card>
  );
}
