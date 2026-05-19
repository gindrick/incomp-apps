# JJA Monitor – konfigurace notifikací
# Vyplň TeamsWebhookUrl, pak spusť register-monitor-task.ps1

# ── Teams Incoming Webhook ──────────────────────────────────────────────────
# Jak vytvořit:
#   Teams → kanál → tři tečky → Connectors → Incoming Webhook → Configure
#   Zkopíruj vygenerovanou URL a vlož sem.
$TeamsWebhookUrl = "https://hranipexcom.webhook.office.com/webhookb2/10ab2d10-3f81-41f6-9c73-ca66212c22f5@73b39313-1d97-4ac4-bc26-f0ba6dc67f1a/IncomingWebhook/abd70e87c47147968dbffb30da938853/89312ca0-529c-49d4-9b64-d7e2958ecda0/V2qiJaD5WjfvGq0MsXv-aw1Z8nJzvMWdmGqDNOlv8GbBA1"    # vlož URL sem

# ── Chování ─────────────────────────────────────────────────────────────────
$AlertCooldownMinutes = 30   # min. pauza mezi alerty pro stejnou službu
$RestartWaitSec       = 12   # čekání po restartu před opakovanou kontrolou


#https://hranipexcom.webhook.office.com/webhookb2/10ab2d10-3f81-41f6-9c73-ca66212c22f5@73b39313-1d97-4ac4-bc26-f0ba6dc67f1a/IncomingWebhook/abd70e87c47147968dbffb30da938853/89312ca0-529c-49d4-9b64-d7e2958ecda0/V2qiJaD5WjfvGq0MsXv-aw1Z8nJzvMWdmGqDNOlv8GbBA1