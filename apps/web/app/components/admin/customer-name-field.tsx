import { Field } from "../ui";

export function CustomerNameField({ defaultValue }: { defaultValue?: string }) {
  return (
    <Field
      label="ФИО заказчика"
      name="display_name"
      required
      pattern={".*\\S.*"}
      maxLength={255}
      defaultValue={defaultValue}
      onInvalid={(event) => {
        if (!event.currentTarget.value.trim())
          event.currentTarget.setCustomValidity("Укажите ФИО заказчика.");
      }}
    />
  );
}
