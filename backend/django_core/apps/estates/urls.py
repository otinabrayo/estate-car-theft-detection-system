from rest_framework.routers import DefaultRouter

from .views import (
    EstateViewSet,
    ApartmentBlockViewSet,
    ApartmentViewSet,
    GateViewSet,
)

router = DefaultRouter()

router.register("estates", EstateViewSet, basename="estate")
router.register("blocks", ApartmentBlockViewSet, basename="block")
router.register("apartments", ApartmentViewSet, basename="apartment")
router.register("gates", GateViewSet, basename="gate")

urlpatterns = router.urls
