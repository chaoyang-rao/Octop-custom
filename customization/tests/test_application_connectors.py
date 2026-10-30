"""Frozen-package regressions for application presets and Slack transport."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from octop.config import OctopConfig
from octop.infra.connectors.builder import build_http_mcp_spec, validate_create_credentials
from octop.infra.connectors.catalog import get_catalog_entry, list_catalog
from octop.infra.gateway.channels.host_channels import register_host_channels
from octop.infra.gateway.channels.slack import SlackChannel, SlackConfig


class ApplicationConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_presets_and_secret_bindings(self):
        self.assertGreaterEqual(len(list_catalog()), 58)
        for kind in ('linear', 'canva', 'trello', 'stripe', 'resend'):
            spec=build_http_mcp_spec(entry=get_catalog_entry(kind),instance_id='test',creds={'access_token':'fake-secret'},config=OctopConfig())
            self.assertEqual(spec['headers']['Authorization'],'Bearer fake-secret')
            self.assertNotIn('fake-secret',spec['url'])
        creds=validate_create_credentials('brave-search',{'api_key':'fake-key'})
        spec=build_http_mcp_spec(entry=get_catalog_entry('brave-search'),instance_id='test',creds=creds,config=OctopConfig())
        self.assertEqual(spec['env']['BRAVE_API_KEY'],'fake-key')
        self.assertNotIn('fake-key',' '.join(spec['args']))

    async def test_slack_ack_filter_and_thread_route(self):
        async def processor(message):
            if False: yield None
        register_host_channels()
        channel=SlackChannel(processor,config=SlackConfig(allowed_channel_ids=['C123']),tenant_id='owned',channel_id='slack1')
        channel._team_id='T123';channel._bot_user_id='UBOT'
        channel._socket=SimpleNamespace(send_json=AsyncMock())
        received=[];channel.set_enqueue_callback(received.append)
        event={'type':'events_api','envelope_id':'receipt','payload':{'team_id':'T123','event':{'type':'app_mention','channel':'C123','user':'U123','ts':'1.001','text':'<@UBOT> hello'}}}
        await channel._handle_envelope(event);await channel._handle_envelope(event)
        self.assertEqual(len(received),1)
        self.assertEqual(received[0].tenant_id,'owned')
        self.assertEqual(received[0].channel_subject.subject_id,'C123:1.001')
        self.assertEqual(channel._socket.send_json.await_count,2)
        channel._socket=None


if __name__=='__main__': unittest.main()
