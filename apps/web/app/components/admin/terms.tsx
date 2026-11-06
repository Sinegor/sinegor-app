import { services } from "../../lib/admin/labels";
import type { Models } from "../../lib/admin/api";
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
    </>
  );
}
export function terms(data: FormData): Models["OrderTerms"] {
  return {
    service_type: text(data, "service_type") as Models["ServiceType"],
  };
}
