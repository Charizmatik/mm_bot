"""Small dynamic protobuf schema for MEXC aggregate book-ticker messages.

The field numbers mirror MEXC's official websocket-proto repository. Keeping the
schema here avoids shipping generated code for unrelated stream types.
"""
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


def _message_class():
    file = descriptor_pb2.FileDescriptorProto(name="mexc_book_ticker.proto", syntax="proto3")
    ticker = file.message_type.add(name="PublicAggreBookTickerV3Api")
    for number, name in enumerate(
        ["bidPrice", "bidQuantity", "askPrice", "askQuantity", "version"], start=1
    ):
        field = ticker.field.add(name=name, number=number, label=1, type=9)
    ticker.field.add(name="lastOrderCreateTime", number=6, label=1, type=3)

    wrapper = file.message_type.add(name="PushDataV3ApiWrapper")
    wrapper.field.add(name="channel", number=1, label=1, type=9)
    body = wrapper.field.add(name="publicAggreBookTicker", number=315, label=1, type=11)
    body.type_name = ".PublicAggreBookTickerV3Api"
    wrapper.field.add(name="symbol", number=3, label=1, type=9)
    wrapper.field.add(name="sendTime", number=6, label=1, type=3)

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("PushDataV3ApiWrapper"))


PushDataV3ApiWrapper = _message_class()


def parse_book_ticker(payload: bytes) -> tuple[str, str, str] | None:
    message = PushDataV3ApiWrapper.FromString(payload)
    ticker = message.publicAggreBookTicker
    if not message.symbol or not ticker.bidPrice or not ticker.askPrice:
        return None
    return message.symbol, ticker.bidPrice, ticker.askPrice

