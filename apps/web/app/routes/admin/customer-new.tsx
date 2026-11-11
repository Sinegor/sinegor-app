import { Link, useNavigate } from "react-router";
import { CustomerNameField } from "../../components/admin/customer-name-field";
import { ApiError } from "../../lib/api/client";
import { value } from "../../lib/admin/api";
import { Field, Button, Card, Form } from "../../components/ui";
import {
  useOperation,
  Feedback,
  formData,
  text,
} from "../../components/admin/common";
export const meta = () => [{ title: "Новый заказчик — SINEGOR LAB" }];
export default function CustomerNew() {
  const op = useOperation(),
    navigate = useNavigate();
  return (
    <>
      <Link to="/admin/customers">← Заказчики</Link>
      <h1>Новый заказчик</h1>
      <Feedback op={op} />
      <Card title="Контактные сведения">
        <p>После создания будет отправлено приглашение в личный кабинет.</p>
        <Form
          method="post"
          busy={op.busy}
          onSubmit={(event) => {
            const data = formData(event);
            void op.run(async (api) => {
              let id: string,
                partial = false;
              try {
                const customer = await value(
                  api.POST("/api/admin/customers", {
                    body: {
                      email: text(data, "email"),
                      display_name: text(data, "display_name"),
                      phone: text(data, "phone") || null,
                    },
                  }),
                );
                id = customer.id;
              } catch (error) {
                if (
                  !(error instanceof ApiError) ||
                  error.status !== 503 ||
                  !error.customerId
                )
                  throw error;
                id = error.customerId;
                partial = true;
              }
              await navigate(
                `/admin/customers/${encodeURIComponent(id)}${partial ? "?invitation=failed" : ""}`,
              );
            }, "");
          }}
        >
          <Field
            label="Email"
            name="email"
            type="email"
            required
            maxLength={320}
            autoComplete="email"
          />
          <CustomerNameField />
          <Field
            label="Телефон"
            name="phone"
            type="tel"
            maxLength={50}
            autoComplete="tel"
          />
          <Button type="submit">Создать и пригласить</Button>
        </Form>
      </Card>
    </>
  );
}
