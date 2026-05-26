# from channels.layers import get_channel_layer
# from asgiref.sync import async_to_sync

# class RealTimeService:
#     """
#     Utility service to broadcast updates to Django Channels groups.
#     """
#     @staticmethod
#     def broadcast_seat_update(event_slug, seats_remaining):
#         """
#         Broadcast the updated seat count to the event's WebSocket group.
#         """
#         channel_layer = get_channel_layer()
#         async_to_sync(channel_layer.group_send)(
#             f"seats_{event_slug}",
#             {
#                 "type": "seat_update",
#                 "seats_remaining": seats_remaining
#             }
#         )
