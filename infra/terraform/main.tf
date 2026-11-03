terraform {
  required_providers {
    databricks = {
      source = "databricks/databricks"
    }
  }
}

provider "databricks" {
  profile = var.databricks_profile   # reuses your CLI login
}

resource "databricks_catalog" "project" {
  name    = "trading_pipeline_e2e_${var.env}"
  comment = "Catalog for Trading_pipeline_E2E (${var.env})"
  # storage_root = var.storage_root   # only if the metastore has no default storage
  properties = {
    project = "trading_pipeline_e2e"
    env     = var.env
  }

  lifecycle {
    prevent_destroy = true   # protects against accidental deletion
    ignore_changes  = [storage_root]
  }
}

# Additive grant: leaves any other grants on the catalog in place
resource "databricks_grant" "engineers" {
  catalog    = databricks_catalog.project.name
  principal  = var.engineer_group
  privileges = ["USE_CATALOG", "CREATE_SCHEMA"]
}