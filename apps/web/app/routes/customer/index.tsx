import { redirect } from "react-router";
export function clientLoader() {
  throw redirect("/customer/orders");
}
export default function CustomerIndex() {
  return null;
}
