import { useToast } from '@nuxt/ui/composables'

type ToastApi = ReturnType<typeof useToast>

function messageFromError(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function toastSuccess(
  toast: ToastApi,
  title: string,
  description?: string,
): void {
  toast.add({
    title,
    description,
    color: 'success',
  })
}

export function toastError(
  toast: ToastApi,
  title: string,
  error: unknown,
  fallback: string,
): void {
  toast.add({
    title,
    description: messageFromError(error, fallback),
    color: 'error',
  })
}

export function toastWarning(
  toast: ToastApi,
  title: string,
  description: string,
): void {
  toast.add({
    title,
    description,
    color: 'warning',
  })
}

export { messageFromError }
