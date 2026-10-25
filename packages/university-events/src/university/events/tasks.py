"""Task registration (autodiscovered by Core): import every task so workers know them."""

from university.events.services.notices import fan_out_notice, send_reminders
from university.events.services.registrations import release_expired_holds

__all__ = ["fan_out_notice", "release_expired_holds", "send_reminders"]
