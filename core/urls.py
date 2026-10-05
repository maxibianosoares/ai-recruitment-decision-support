from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [

    path(
        'admin/',
        admin.site.urls
    ),

    path(
        'accounts/',
        include('accounts.urls')
    ),
    path(
        'recruitment/',
        include('recruitment.urls')
    ),

    path(
        '',
        include('talent.urls')
    ),
    path(
    "",
    include("ai_engine.urls")
),  

]

# SECURITY FIX (FINAL FINISHING SESSION, 2026-10-05, Section 26 file
# security audit): this helper was wired in unconditionally, so in
# production (DEBUG=False on Render) uploaded candidate CVs under
# /media/ were served to ANYONE with the URL, with no authentication
# or ownership check at all -- "do not make uploaded CVs publicly
# accessible" was being violated. No template in this project links
# to cv_file.url directly (confirmed by inspection), so nothing
# legitimate relies on this being public. Gating it to DEBUG-only is
# the standard Django pattern (this static-file helper is documented
# as a local-development convenience, never a production file
# server) -- in production this simply stops serving /media/* at
# all, which is the safe default; CVs remain reachable through the
# existing authenticated Candidate Detail page / admin, which never
# depended on this raw media route.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )