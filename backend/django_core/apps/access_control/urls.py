from django.urls import path

from .views import (
    GateEntryAPIView,
    GateExitAPIView,
    VehicleMovementSessionListAPIView,
    GateAccessEventListAPIView,
)

urlpatterns = [
    path(
        "gate-access/entry/",
        GateEntryAPIView.as_view(),
        name="gate-entry",
    ),
    path(
        "gate-access/exit/",
        GateExitAPIView.as_view(),
        name="gate-exit",
    ),
    path(
        "movement-sessions/",
        VehicleMovementSessionListAPIView.as_view(),
        name="movement-sessions",
    ),
    path(
        "gate-events/",
        GateAccessEventListAPIView.as_view(),
        name="gate-events",
    ),
]
