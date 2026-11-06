import type { Models } from "./api";
export const statuses: Record<Models["OrderStatus"], string> = {
  awaiting_agreement: "Ожидает оформления",
  awaiting_materials: "Ожидает материалы",
  in_progress: "В работе",
  result_ready: "Результат готов",
  completed: "Завершён",
  cancelled: "Отменён",
};
export const services: Record<Models["ServiceType"], string> = {
  analysis: "ИИ-анализ документов",
  technical_preparation: "Техническая подготовка",
};
export const agreements: Record<Models["AgreementStatus"], string> = {
  awaiting_customer: "Ожидает подписи заказчика",
  under_review: "На проверке",
  approved: "Утверждено",
  rejected: "Отклонено",
};
export const deletions: Record<Models["DeletionStatus"], string> = {
  waiting: "Ожидает решения",
  deferred: "Отложено",
  confirmed: "Решение подтверждено",
  error: "Ошибка операции",
  performed: "Удаление проверено",
};
export function date(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("ru-RU", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Europe/Moscow",
      }).format(new Date(value)) + " МСК"
    : "—";
}
export const eventLabels: Record<string, string> = {
  customer_created: "Заказчик создан",
  customer_updated: "Карточка заказчика изменена",
  order_created: "Заказ создан",
  terms_updated: "Условия изменены",
  payment_confirmed: "Оплата подтверждена",
  materials_submitted: "Заказчик передал материалы",
  agreement_initial_uploaded: "Загружен PDF исполнителя",
  agreement_returned_uploaded: "Получен PDF заказчика",
  agreement_approved: "Соглашение утверждено",
  agreement_rejected: "Соглашение отклонено",
  status_awaiting_materials: "Заказ ожидает материалы",
  status_in_progress: "Заказ принят в работу",
  status_result_ready: "Результат готов",
  status_completed: "Заказ завершён",
  status_cancelled: "Заказ отменён",
  result_notification_sent: "Письмо о готовности принято SMTP",
  agreement_initial_downloaded: "Скачан PDF исполнителя",
  agreement_returned_downloaded: "Скачан PDF заказчика",
  agreement_final_downloaded: "Скачан окончательный PDF",
  agreement_file_deleted: "Удалён временный PDF",
  disk_folder_bound: "Папка создана или привязана",
  disk_folder_identity_verified: "Идентичность папки проверена",
  deletion_requested: "Создан запрос удаления",
  deletion_early_authorized: "Получено досрочное разрешение заказчика",
  deletion_confirmed: "Решение об удалении подтверждено",
  deletion_deferred: "Удаление отложено",
  deletion_deferral_expired: "Истекла отсрочка удаления",
  disk_deletion_started: "Операция удаления начата",
  disk_deletion_failed: "Ошибка операции удаления",
  disk_deletion_manually_verified: "Окончательное удаление проверено вручную",
  disk_folder_deleted: "Удаление папки проверено",
  disk_folder_link_updated: "Клиентская ссылка сохранена",
};
