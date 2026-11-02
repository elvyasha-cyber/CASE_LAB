"""Адаптеры входа и доставки. Демо работает на files; http/mail/email — точки подключения."""

from case_lab.adapters.base import AdapterNotConfigured, ProcessResult
from case_lab.adapters.inbox_files import load_file_inbox
from case_lab.adapters.notify_manager import notify_manager

__all__ = [
    "AdapterNotConfigured",
    "ProcessResult",
    "load_file_inbox",
    "notify_manager",
]
