from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    SecurityAlertViewSet,
    OwnerConfirmationInternalCreateAPIView,
    OwnerConfirmationListAPIView,
    OwnerConfirmationRespondAPIView,
    OwnerConfirmationInternalStatusAPIView,
)

router = DefaultRouter()

router.register(
    "security-alerts",
    SecurityAlertViewSet,
    basename="security-alert",
)

urlpatterns = [
    path(
        "internal/owner-confirmations/",
        OwnerConfirmationInternalCreateAPIView.as_view(),
        name="internal-owner-confirmation-create",
    ),

    path(
        "owner-confirmations/",
        OwnerConfirmationListAPIView.as_view(),
        name="owner-confirmation-list",
    ),

    path(
        "owner-confirmations/<uuid:pk>/respond/",
        OwnerConfirmationRespondAPIView.as_view(),
        name="owner-confirmation-respond",
    ),
    path(
        "internal/owner-confirmations/<uuid:event_id>/",
        OwnerConfirmationInternalStatusAPIView.as_view(),
        name="internal-owner-confirmation-status",
    ),
]

urlpatterns += router.urls
