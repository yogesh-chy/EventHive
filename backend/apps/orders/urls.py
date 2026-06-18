from django.urls import path
from .views import OrderViewSet

order_list    = OrderViewSet.as_view({"get": "list",     "post": "create"})
order_detail  = OrderViewSet.as_view({"get": "retrieve"})
order_cancel  = OrderViewSet.as_view({"post": "cancel"})
order_confirm = OrderViewSet.as_view({"post": "confirm"})

urlpatterns = [
    path("",                      order_list,    name="order-list"),
    path("<uuid:id>/",            order_detail,  name="order-detail"),
    path("<uuid:id>/cancel/",     order_cancel,  name="order-cancel"),
    path("<uuid:id>/confirm/",    order_confirm, name="order-confirm"),
]