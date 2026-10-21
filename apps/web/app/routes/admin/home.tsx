import { redirect } from "react-router";
export function clientLoader() {
  throw redirect("/admin/customers");
}
export default function AdminHome() {
  return null;
}
