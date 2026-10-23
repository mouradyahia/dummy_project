# -*- coding: utf-8 -*-
# compute_rul_direct_debits_details_v1 — solution A, all code in the recipe (no COR.rules import).
#
# Each month: read photo M of the 7 prep datasets (country partition), recompute the lines whose
# direct debit date falls in emission months M-5 .. M, write them. Groups / attempt order are
# computed on the whole photo (15 months of debits) with window functions, never read from the
# Data Product. PRODUCT then replaces the PostgreSQL partitions country x month in one transaction.
#
# Column names marked "TO CONFIRM" come from the specs, not from an opened table.

import dataiku
from dataiku import spark as dkuspark
from pyspark import SparkContext
from pyspark.sql import SQLContext, Window
from pyspark.sql import functions as F

from COR.prep import get_partition_value          # same helper as the hst recipes

# ------------------------------------------------------------------ config
V = dataiku.get_custom_variables()
RECOMPUTE_MONTHS = int(V.get("recompute_months", 6))    # M-5 .. M are rewritten
GROUP_BY_LOT     = V.get("group_by_lot", "0") == "1"    # Q6 open: 0 = per invoice (rule 5, slides), 1 = invoice + lot (rule 4)
INVOICE_PREFIX   = "FLL"                                # rent invoices only
# CASH_FLOW filters "direct debit" and "incoming / credit": the column names are not in the specs
# we hold, and DCP may already apply them (open question). Fill once the table is open. {} = no filter.
CASH_FLOW_FILTERS = {
    # "cod_cash_flow_type": ["DIRECT_DEBIT"],          # TO CONFIRM
    # "cod_cash_flow_direction": ["CREDIT"],           # TO CONFIRM
}

DS = "PHASE2_01_COR_DATASET."
SRC = {
    "invoice":             DS + "prep_cash_flow_ctr_fin_cdt_invoice_monthly_v1",
    "cash_flow":           DS + "prep_cash_flow_monthly_v1",
    "direct_debit":        DS + "prep_direct_debit_cash_flow_monthly_v1",
    "failed":              DS + "prep_failed_cash_flow_monthly_v1",
    "failure_reason":      DS + "prep_typ_cash_flow_failure_reason_monthly_v1",
    "financing_condition": DS + "prep_c_leasing_financing_condition_monthly_v1",
    "market":              DS + "prep_marche_ibl_ctrqtd_monthly_v1",
}
OUT = "rul_direct_debits_details_v1"

K3 = ["cod_country", "cod_business_type", "id_cash_flow"]          # the "triplet" of rules 1, 3, 6, 8
PK = K3 + ["id_leasing_contract", "id_leasing_fin_cdt", "id_leasing_invoice"]   # DETAILS primary key (6)


# ------------------------------------------------------------------ rules
def build_details(inv, cf, dd, fail, rsn, fc, mkt, photo_date):
    """Pure function: 7 DataFrames of ONE photo and ONE country -> DETAILS lines of months M-5..M.

    inv : cod_country, cod_business_type, id_cash_flow, id_leasing_contract, id_leasing_fin_cdt,
          id_leasing_invoice, mt_direct_debit
    cf  : cod_country, cod_business_type, id_cash_flow (+ filter columns)
    dd  : cod_country, cod_business_type, id_cash_flow, dt_direct_debit (date)
    fail: cod_country, cod_business_type, id_cash_flow, dt_failure (date), cod_cash_flow_failure_reason
    rsn : cod_country, cod_business_type, cod_cash_flow_failure_reason, lib_cash_flow_failure_reason
    fc  : cod_country, cod_business_type, id_leasing_contract, id_leasing_fin_cdt, cod_rent_payment_frequency
    mkt : id_leasing_contract, marche_code, marche, ibl, dtvaleur   (already the country of the partition)
    """
    # 1. filters (specs: direct debit, incoming, rent invoice FLL; 'L' rows already removed by DCP)
    inv = inv.filter(F.col("id_leasing_invoice").startswith(INVOICE_PREFIX))
    for col, values in CASH_FLOW_FILTERS.items():
        cf = cf.filter(F.col(col).isin(values))
    cf = cf.select(*K3).distinct()
    dd = dd.groupBy(*K3).agg(F.min("dt_direct_debit").alias("dt_direct_debit"))   # one date per debit

    # 2. one line per debit x contract x lot x invoice, dated by its debit (inner: no date -> no month -> dropped)
    base = inv.join(cf, K3).join(dd, K3)

    # 3. groups and attempt order (rules 4, 5, 6) on the whole photo, computed from the photo only
    grp_key = ["cod_country", "cod_business_type", "id_leasing_invoice"] + (["id_leasing_fin_cdt"] if GROUP_BY_LOT else [])
    pairs = base.select(*grp_key, "id_cash_flow", "dt_direct_debit").distinct()
    w_inv = Window.partitionBy(*grp_key).orderBy("dt_direct_debit", "id_cash_flow")
    pairs = (pairs
             .withColumn("ord_inv", F.row_number().over(w_inv))               # rank of this debit on this invoice
             .withColumn("grp_inv", F.first("id_cash_flow").over(w_inv))      # id of the first debit on this invoice
             .withColumn("dt0_inv", F.first("dt_direct_debit").over(w_inv)))  # date of that first debit
    # a debit covering several invoices takes the rank of the invoice with the longest history (slide 22);
    # an invoice added to a re-debit (never debited before) keeps that group / order with all flags 0 (Q5)
    w_dd = Window.partitionBy(*K3).rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)
    pairs = pairs.withColumn("num_order_in_group", F.max("ord_inv").over(w_dd))
    on_max = F.col("ord_inv") == F.col("num_order_in_group")
    pairs = (pairs
             .withColumn("id_group", F.min(F.when(on_max, F.col("grp_inv"))).over(w_dd))
             .withColumn("dt_initial_direct_debit", F.min(F.when(on_max, F.col("dt0_inv"))).over(w_dd))
             .withColumn("flg_added_invoice", (~on_max).cast("int"))
             .drop("ord_inv", "grp_inv", "dt0_inv", "dt_direct_debit"))
    base = base.join(pairs, grp_key + ["id_cash_flow"])

    # amount of the initial debit, copied on every line of the group (asked in the review, +0.5 d)
    dd_amount = base.groupBy(*K3).agg(F.sum("mt_direct_debit").alias("mt_initial_direct_debit")) \
                    .withColumnRenamed("id_cash_flow", "id_group")
    base = base.join(dd_amount, ["cod_country", "cod_business_type", "id_group"], "left")

    # 4. failures (rules 1, 2, 3): one failure per debit expected (slide 6); keep the latest if not
    w_f = Window.partitionBy(*K3).orderBy(F.col("dt_failure").desc())
    fail = fail.withColumn("rn", F.row_number().over(w_f)).filter("rn = 1").drop("rn")
    rsn = rsn.dropDuplicates(["cod_country", "cod_business_type", "cod_cash_flow_failure_reason"])
    fail = fail.join(rsn, ["cod_country", "cod_business_type", "cod_cash_flow_failure_reason"], "left")
    base = base.join(fail, K3, "left")

    # 5. periodicity (lot level), market / IBL (contract level): last known value, then frozen with the month
    fc = fc.dropDuplicates(["cod_country", "cod_business_type", "id_leasing_contract", "id_leasing_fin_cdt"])
    base = base.join(fc, ["cod_country", "cod_business_type", "id_leasing_contract", "id_leasing_fin_cdt"], "left")
    w_m = Window.partitionBy("id_leasing_contract").orderBy(F.col("dtvaleur").desc_nulls_last())
    mkt = mkt.withColumn("rn", F.row_number().over(w_m)).filter("rn = 1").drop("rn", "dtvaleur")
    base = base.join(mkt, ["id_leasing_contract"], "left")     # same country: the partition

    # 6. the 6 indicators (rules 7..12): order 1 = DD, 2 = NDD1, 3 = NDD2, > 3 not flagged (validated)
    failed = F.col("dt_failure").isNotNull()
    def flag(order, cond):
        return F.when((F.col("flg_added_invoice") == 0) & (F.col("num_order_in_group") == order) & cond, 1).otherwise(0)
    base = (base
            .withColumn("flg_dd_emitted",   flag(1, F.lit(True)))
            .withColumn("flg_dd_failed",    flag(1, failed))
            .withColumn("flg_ndd1_emitted", flag(2, F.lit(True)))
            .withColumn("flg_ndd1_failed",  flag(2, failed))
            .withColumn("flg_ndd2_emitted", flag(3, F.lit(True)))
            .withColumn("flg_ndd2_failed",  flag(3, failed)))

    # 7. keep only the recompute window M-5 .. M (older months are frozen in the Data Product)
    m_first = F.trunc(F.lit(photo_date).cast("date"), "month")
    out = base.filter((F.col("dt_direct_debit") >= F.add_months(m_first, -(RECOMPUTE_MONTHS - 1))) &
                      (F.col("dt_direct_debit") <  F.add_months(m_first, 1)))

    return out.select(
        *PK,
        "dt_direct_debit", "mt_direct_debit",
        "dt_failure", "cod_cash_flow_failure_reason", "lib_cash_flow_failure_reason",
        F.col("cod_rent_payment_frequency").alias("lib_financing_condition_recurrence"),
        F.col("marche_code").alias("cod_contract_ibl_market"),
        F.col("marche").alias("lib_contract_ibl_market"),
        F.col("ibl").alias("lib_contract_ibl"),
        "id_group", "num_order_in_group", "dt_initial_direct_debit", "mt_initial_direct_debit", "flg_added_invoice",
        "flg_dd_emitted", "flg_dd_failed", "flg_ndd1_emitted", "flg_ndd1_failed", "flg_ndd2_emitted", "flg_ndd2_failed",
        F.date_format("dt_direct_debit", "yyyy-MM").alias("mois_emission"),
        F.lit(photo_date).cast("date").alias("tech_photo_date"),
        F.current_timestamp().alias("tech_ingestion_ts"),
    )


# ------------------------------------------------------------------ Dataiku glue
if __name__ == "__main__":
    sc = SparkContext.getOrCreate()
    sql = SQLContext(sc)
    country = get_partition_value("country")
    photo_date = get_partition_value("photo_date")                 # 'YYYY-MM-DD', photo M
    print(f"[details] {OUT} | partition {country}|{photo_date} | window {RECOMPUTE_MONTHS} months")

    def read(key, renames):
        df = dkuspark.get_dataframe(sql, dataiku.Dataset(SRC[key]))
        df = df.filter((F.date_format("tech_photo_date", "yyyy-MM-dd") == photo_date) &
                       (F.col("tech_country_partition") == country))
        for old, new in renames.items():
            df = df.withColumnRenamed(old, new)
        return df

    inv = read("invoice", {"cod_country_iso3_cash_flow": "cod_country", "cod_business_type_cash_flow": "cod_business_type"}) \
        .select(*PK, F.col("mt_settled").cast("decimal(18,2)").alias("mt_direct_debit"))          # mt_settled: TO CONFIRM
    cf = read("cash_flow", {"cod_country_iso3_cash_flow": "cod_country", "cod_business_type_cash_flow": "cod_business_type"}) \
        .select(*K3, *CASH_FLOW_FILTERS.keys())
    dd = read("direct_debit", {"cod_country_iso3_direct_debit_cash_flow": "cod_country",
                               "cod_business_type_direct_debit_cash_flow": "cod_business_type",
                               "id_direct_debit_cash_flow": "id_cash_flow"}) \
        .select(*K3, F.to_date("dt_direct_debit").alias("dt_direct_debit"))
    fail = read("failed", {"cod_country_iso3_failed_cash_flow": "cod_country", "cod_business_type_failed_cash_flow": "cod_business_type"}) \
        .select(*K3, F.to_date("dt_cash_flow_failure_recording").alias("dt_failure"), "cod_cash_flow_failure_reason")   # TO CONFIRM
    rsn = read("failure_reason", {"cod_country_iso3_cash_flow_failure_reason": "cod_country",
                                  "cod_business_type_cash_flow_failure_reason": "cod_business_type"}) \
        .select("cod_country", "cod_business_type", "cod_cash_flow_failure_reason", "lib_cash_flow_failure_reason")
    fc = read("financing_condition", {"cod_country_iso3_leasing_fin_cdt": "cod_country", "cod_business_type_leasing_fin_cdt": "cod_business_type"}) \
        .select("cod_country", "cod_business_type", "id_leasing_contract", "id_leasing_fin_cdt", "cod_rent_payment_frequency")   # TO CONFIRM
    mkt = read("market", {}) \
        .select(F.col("contrat_code").alias("id_leasing_contract"), "marche_code", "marche", "ibl", F.to_date("dtvaleur").alias("dtvaleur"))

    out = build_details(inv, cf, dd, fail, rsn, fc, mkt, photo_date).cache()

    # controls before writing: not empty, PK unique (decided: uniqueness check at each load)
    n = out.count()
    dups = out.groupBy(*PK).count().filter("count > 1").count()
    print(f"[details] {n} lines, {dups} duplicate keys")
    if n == 0:
        raise RuntimeError(f"[details] empty result for {country}|{photo_date}: photo missing or filters wrong, nothing written")
    if dups:
        raise RuntimeError(f"[details] {dups} duplicate DETAILS keys, nothing written")

    dkuspark.write_with_schema(dataiku.Dataset(OUT), out)
