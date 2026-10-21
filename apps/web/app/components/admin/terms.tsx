import { services } from "../../lib/admin/labels";
import type { Models } from "../../lib/admin/api";
import { Field } from "../ui";
import { SelectField, text } from "./common";
export function TermsFields({ order }: { order?: Models["OrderRead"] }) {
  return (
    <>
      <SelectField
        label="Услуга"
        name="service_type"
        value={order?.service_type ?? "analysis"}
        required
      >
        {Object.entries(services).map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </SelectField>
      <label className="field">
        Согласованные условия
        <textarea
          name="description"
          rows={5}
          maxLength={10000}
          defaultValue={order?.description ?? ""}
        />
      </label>
      <Field
        label="Согласованная стоимость, ₽ (необязательно)"
        name="agreed_price"
        inputMode="decimal"
        pattern="[0-9]{1,10}([.,][0-9]{1,2})?"
        defaultValue={order?.agreed_price ?? ""}
      />
    </>
  );
}
export function terms(data: FormData): Models["OrderTerms"] {
  return {
    service_type: text(data, "service_type") as Models["ServiceType"],
    description: text(data, "description") || null,
    agreed_price: text(data, "agreed_price").replace(",", ".") || null,
  };
}
