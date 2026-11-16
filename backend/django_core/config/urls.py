from django.contrib import admin
from django.urls import path, include

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


urlpatterns = [
    path("admin/", admin.site.urls),

    path(
        "api/v1/auth/token/",
        TokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),

    path(
        "api/v1/auth/token/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),

    path("api/v1/", include("apps.estates.urls")),
    path("api/v1/", include("apps.residents.urls")),
    path("api/v1/", include("apps.vehicles.urls")),
    path("api/v1/", include("apps.visitors.urls")),
    path("api/v1/", include("apps.access_control.urls")),
    path("api/v1/", include("apps.alerts.urls")),
]
