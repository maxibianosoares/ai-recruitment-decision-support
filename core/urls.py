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

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)