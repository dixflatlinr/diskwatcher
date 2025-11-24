import dbus

class Notifier:
    """Handles desktop notifications via DBus"""

    SERVICE = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"
    INTERFACE = "org.freedesktop.Notifications"

    ERROR_LEVELS = \
    {
        "low":
        {
            'urgency': 0,
            'app_icon': 'drive-harddisk'
        },
        "normal":
        {
            'urgency': 1,
            'app_icon': 'drive-harddisk'
        },
        "critical":
        {
            'urgency': 2,
            'app_icon': 'error'
        },
    }

    def __init__(self, options = None):
        if options is None:
            self.options = {'die_on_error': False}

        try:
            bus = dbus.SessionBus()
            obj = bus.get_object(self.SERVICE, self.PATH)
            self.interface = dbus.Interface(obj, self.INTERFACE)
        except Exception as e:
            if self.options.get('die_on_error'):
                raise RuntimeError(f"Dbus notification unavailable: {e}")
            else:
                pass

    def send(self, app_name:str, message:str, error_level:str = 'critical', timeout_ms:int = 10000):
        # https://specifications.freedesktop.org/notification-spec/notification-spec-latest.html#urgency-levels
        # urgency = 0=low, 1=normal, 2=critical
        # https://pychao.com/2021/03/01/sending-desktop-notification-in-linux-with-python-with-d-bus-directly/

        error_data = self.ERROR_LEVELS.get(error_level)

        # Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout)
        self.interface.Notify(
            app_name,
            0,
            error_data['app_icon'],
            app_name,
            message,
            [],
            {"urgency": error_data['urgency']},
            timeout_ms
        )

