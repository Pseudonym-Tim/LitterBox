"""Change APP_VERSION here when making a release..."""

APP_VERSION = '1.2.1'
APP_VERSION_DISPLAY = f'v{APP_VERSION}'

def versioned_title(title):
    return f'{title} {APP_VERSION_DISPLAY}'