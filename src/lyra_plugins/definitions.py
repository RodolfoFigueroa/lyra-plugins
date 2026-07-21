from lyra.sdk import PluginDefinition

from lyra_plugins.metrics.accessibility_jobs import metric as accessibility_jobs_metric


def create_plugin() -> PluginDefinition:
    return PluginDefinition(metrics=[accessibility_jobs_metric])
