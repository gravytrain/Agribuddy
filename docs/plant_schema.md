# Canonical Plant Variety Schema

This document defines the unified data contract for plant variety reference data
across all providers (CSV dataset, AI fallback, legacy Verdantly cache) and
consumers (Agribuddy card, FarmOS sync, Home Assistant sensors).

## Canonical Fields

Every provider MUST return data in this shape. Consumers read ONLY this shape.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `variety_id` | string | yes | Unique identifier (slug or UUID) |
| `name` | string | yes | Variety/cultivar name (e.g., "Cherokee Purple") |
| `category` | string | yes | Plant category (e.g., "tomato", "herb", "pepper") |
| `scientific_name` | string | no | Binomial name (e.g., "Solanum lycopersicum") |
| `description` | string | no | General description of the variety |
| `image_url` | string \| null | no | URL to a representative image |
| **Growing Requirements** | | | |
| `days_to_harvest_min` | int \| null | no | Minimum days from planting to harvest |
| `days_to_harvest_max` | int \| null | no | Maximum days from planting to harvest |
| `days_to_germination_min` | int \| null | no | Minimum germination days |
| `days_to_germination_max` | int \| null | no | Maximum germination days |
| `sun_requirement` | string | no | e.g., "Full sun (6+ hours)", "Partial shade" |
| `water_requirement` | string | no | e.g., "High", "Moderate", "Low" |
| `soil_type` | string | no | e.g., "Rich, well-drained loam" |
| `soil_ph_min` | float \| null | no | Minimum pH tolerance |
| `soil_ph_max` | float \| null | no | Maximum pH tolerance |
| `plant_spacing` | string | no | e.g., "24-36 inches" |
| `plant_height` | string | no | e.g., "1-10 feet" |
| `usda_zone_min` | int \| null | no | Minimum USDA hardiness zone |
| `usda_zone_max` | int \| null | no | Maximum USDA hardiness zone |
| `growing_season` | string | no | e.g., "Warm season annual" |
| `sowing_method` | string | no | Planting instructions |
| `growing_difficulty` | string | no | e.g., "Easy", "Moderate", "Difficult" |
| `is_container_friendly` | bool | no | Can grow in containers |
| **Resistance & Threats** | | | |
| `disease_resistance` | string | no | Description of resistance traits |
| `common_pests` | string | no | Known pest threats |
| `common_diseases` | string | no | Known disease threats |
| **Safety & Ecology** | | | |
| `toxicity` | dict \| null | no | Keyed by species (humans, dogs, cats, etc.), value is level |
| `is_invasive` | bool | no | Whether the plant is invasive |
| **Variety Characteristics** | | | |
| `color` | string | no | Fruit/flower/foliage color |
| `size` | string | no | Fruit/plant size |
| `shape` | string | no | Growth habit or fruit shape |
| `flavor_profile` | string | no | Taste description |
| `culinary_uses` | string | no | Cooking/eating applications |
| `is_heirloom` | bool | no | Whether it's an heirloom variety |
| `is_hybrid` | bool | no | Whether it's a hybrid |
| **Metadata** | | | |
| `source` | string | yes | Provider that supplied this data ("csv", "ai", "verdantly") |
| `source_url` | string \| null | no | Attribution/reference URL |
| `confidence` | float | no | 0.0-1.0, how confident we are in accuracy (1.0 for CSV/authoritative, 0.7-0.9 for AI) |

## Related Data (separate lookups, keyed by variety_id + zone)

### Planting Calendar

| Field | Type | Description |
|-------|------|-------------|
| `variety_id` | string | FK to variety |
| `usda_zone` | int | Zone this schedule applies to |
| `indoor_sow_start` | string \| null | Month to start indoor sowing |
| `indoor_sow_end` | string \| null | Month to stop indoor sowing |
| `outdoor_transplant_start` | string \| null | Month to begin transplanting |
| `outdoor_transplant_end` | string \| null | Month to stop transplanting |
| `direct_sow_start` | string \| null | Month to begin direct sowing |
| `direct_sow_end` | string \| null | Month to stop direct sowing |
| `harvest_start` | string \| null | Month harvest begins |
| `harvest_end` | string \| null | Month harvest ends |

### Companion Plants

| Field | Type | Description |
|-------|------|-------------|
| `variety_id` | string | FK to variety |
| `companion_name` | string | Name of the companion plant |
| `relationship` | string | "beneficial" or "antagonistic" |
| `reason` | string | Why this relationship exists |

## Provider Mapping

### CSV Dataset → Canonical

| CSV Field | Canonical Field | Transform |
|-----------|----------------|-----------|
| `id` | `variety_id` | Use slug (more stable than int id) |
| `name` | `name` | Direct |
| `category` | `category` | Direct |
| `scientific_name` | `scientific_name` | Direct |
| `description` | `description` | Direct |
| `days_to_harvest` | `days_to_harvest_min/max` | Parse "70-75" → min=70, max=75; "72" → min=72, max=72 |
| `days_to_germination` | `days_to_germination_min/max` | Parse "7-14" → min=7, max=14 |
| `sun_requirement` | `sun_requirement` | Direct |
| `water_requirement` | `water_requirement` | Direct |
| `soil_type` | `soil_type` | Direct |
| `soil_ph` | `soil_ph_min/max` | Parse "6.2-6.8" → min=6.2, max=6.8 |
| `plant_spacing` | `plant_spacing` | Direct |
| `plant_height` | `plant_height` | Direct |
| `usda_zone_min` | `usda_zone_min` | Direct (int) |
| `usda_zone_max` | `usda_zone_max` | Direct (int) |
| `growing_season` | `growing_season` | Direct |
| `sowing_method` | `sowing_method` | Direct |
| `growing_difficulty` | `growing_difficulty` | Direct |
| `is_container_friendly` | `is_container_friendly` | Parse "true"/"false" → bool |
| `disease_resistance` | `disease_resistance` | Direct |
| `common_pests` | `common_pests` | Direct |
| `common_diseases` | `common_diseases` | Direct |
| `color` | `color` | Direct |
| `size` | `size` | Direct |
| `shape` | `shape` | Direct |
| `flavor_profile` | `flavor_profile` | Direct |
| `culinary_uses` | `culinary_uses` | Direct |
| `is_heirloom` | `is_heirloom` | Parse "true"/"false" → bool |
| `is_hybrid` | `is_hybrid` | Parse "true"/"false" → bool |
| `source_database` | `source` | Set to "csv" (keep original as source_url) |
| `url` | `source_url` | Direct |

### AI Fallback → Canonical

The AI provider receives a prompt that specifies this exact schema and returns
JSON matching it directly. `source` = "ai", `confidence` = 0.7-0.9 depending on
how common the variety is.

### Legacy Verdantly → Canonical

For existing plants that have cached `species_data`:

| Verdantly Path | Canonical Field |
|----------------|----------------|
| `id` | `variety_id` |
| `name` | `name` |
| `species.scientificName` | `scientific_name` |
| `growingRequirements.sunlightRequirement` | `sun_requirement` |
| `growingRequirements.waterRequirement` | `water_requirement` |
| `growingRequirements.soilPreference` | `soil_type` |
| `growingRequirements.spacingRequirement` | `plant_spacing` |
| `growingRequirements.minGrowingZone` | `usda_zone_min` |
| `growingRequirements.maxGrowingZone` | `usda_zone_max` |
| `growingRequirements.careInstructions` | `sowing_method` |
| `ecology.soilPhMin` | `soil_ph_min` |
| `ecology.soilPhMax` | `soil_ph_max` |
| `ecology.isInvasive` | `is_invasive` |
| `lifecycleMilestones.daysToHarvestMin` | `days_to_harvest_min` |
| `lifecycleMilestones.daysToHarvestMax` | `days_to_harvest_max` |
| `safety.toxicity` | `toxicity` |
| `imageUrl` | `image_url` |
| `description` | `description` |

### Canonical → FarmOS plant_type Taxonomy Term

Core fields (built-in to FarmOS):

| Canonical Field | FarmOS Field | Notes |
|----------------|--------------|-------|
| `name` | `name` | Term name |
| `description` | `description` | Term description |
| `days_to_harvest_min` | `maturity_days` | Use min value |
| `days_to_germination_max` | `transplant_days` | If transplant module enabled |

Custom fields (requires `farm_plant_reference` module):

| Canonical Field | FarmOS Custom Field | Field Type |
|----------------|---------------------|------------|
| `sun_requirement` | `sun_requirement` | string |
| `water_requirement` | `water_requirement` | list_string (Low/Moderate/High) |
| `soil_type` | `soil_type` | string |
| `soil_ph_min` | `soil_ph_min` | decimal |
| `soil_ph_max` | `soil_ph_max` | decimal |
| `plant_spacing` | `plant_spacing` | string |
| `plant_height` | `plant_height` | string |
| `usda_zone_min` | `usda_zone_min` | integer |
| `usda_zone_max` | `usda_zone_max` | integer |
| `growing_season` | `growing_season` | string |
| `sowing_method` | `sowing_method` | text_long |
| `growing_difficulty` | `growing_difficulty` | list_string (Easy/Moderate/Difficult) |
| `is_container_friendly` | `container_friendly` | boolean |
| `disease_resistance` | `disease_resistance` | text_long |
| `common_pests` | `common_pests` | string |
| `common_diseases` | `common_diseases` | string |
| `is_invasive` | `is_invasive` | boolean |
| `is_heirloom` | `is_heirloom` | boolean |
| `source` | `data` | Store full metadata JSON in the API-only data field |

### Canonical → Agribuddy Enriched Plant

The `_enrich()` method in store.py reads from `species_data` and produces display
fields. With the new architecture, `species_data` will contain the canonical
schema directly (no more nested Verdantly structure). The enrichment logic
simplifies to:

| Canonical Field | Agribuddy Display Field | Transform |
|----------------|------------------------|-----------|
| `name` | `common_name`, `variety_name` | Direct |
| `scientific_name` | `scientific_name` | Direct |
| `sun_requirement` | `light_requirements` | Direct |
| `water_requirement` | `water_use` | Direct; also map to day ranges |
| `soil_type` | `soil_preference` | Direct |
| `soil_ph_min/max` | `soil_ph_range` | Format "6.2–6.8" |
| `usda_zone_min/max` | `hardiness_zone_range` | Format "7–9" |
| `days_to_harvest_min/max` | `harvest_range` | Format "70–75 days" |
| `is_invasive` | `invasive_alert` | Direct bool |
| `toxicity` | `toxicity_display` | Filter benign levels, format string |
| `image_url` | `image_url` | Direct |
| `plant_spacing` | `spacing_requirement` | Direct |
| `description` | `description` | Direct |
