"""Octop-owned transports registered alongside the gateway's builtin kinds."""

from octop_gateway.channels import register_channel_kind

from octop.infra.gateway.channels.slack import SlackChannel

HOST_CHANNEL_KINDS = frozenset({"slack"})


def register_host_channels() -> None:
    register_channel_kind("slack", SlackChannel, plugin_id="octop.host.slack")
