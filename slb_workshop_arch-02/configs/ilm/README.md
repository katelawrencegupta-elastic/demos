{
  "_meta": {
    "do_not_put_on_serverless": true,
    "description": "Hosted / self-managed mapping of ARCH-02 retention classes. ILM APIs are unavailable on this Serverless project."
  },
  "classes": {
    "platform_metrics": {
      "data_retention_serverless": "7d",
      "ilm_policy": "arch02-metrics-hot-delete",
      "phases": "hot 0d → delete 7d"
    },
    "application_logs": {
      "data_retention_serverless": "30d (14d nonprod)",
      "ilm_policy": "arch02-logs-hot-warm-delete",
      "phases": "hot 0d → warm 7d → delete 30d"
    },
    "audit_security": {
      "data_retention_serverless": "90d (stand-in for 1y+ compliance)",
      "ilm_policy": "arch02-audit-hot-warm-cold-frozen",
      "phases": "hot 0d → warm 7d → cold 30d → frozen 90d → delete 365d"
    },
    "traces_sampled": {
      "data_retention_serverless": "3d",
      "ilm_policy": "arch02-traces-hot-delete",
      "phases": "hot 0d → delete 3d"
    }
  }
}
