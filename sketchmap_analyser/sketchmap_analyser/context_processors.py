import os
from datetime import datetime

import pytz

_REPO_URL = 'https://github.com/ifgi-sil/SketchMapia-Microservices'
_BERLIN = pytz.timezone('Europe/Berlin')


def version_info(request):
    """Expose the build's git tag/commit (baked into the image by CI) to templates."""
    tag = os.environ.get('GIT_TAG', '')
    sha = os.environ.get('GIT_SHA', '')
    date_raw = os.environ.get('GIT_COMMIT_DATE', '')

    date_display = ''
    if date_raw:
        try:
            dt = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
            date_display = dt.astimezone(_BERLIN).strftime('%Y.%m.%d %H:%M')
        except ValueError:
            date_display = date_raw

    if tag:
        version = tag
        version_url = f'{_REPO_URL}/releases/tag/{tag}'
    elif sha:
        version = sha[:7]
        version_url = f'{_REPO_URL}/commit/{sha}'
    else:
        version = ''
        version_url = ''

    return {
        'APP_VERSION': version,
        'VERSION_URL': version_url,
        'GIT_COMMIT_DATE': date_display,
    }
