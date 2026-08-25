TV_SQL = '''
SELECT
    region.regionName as region_tv,
    dur.adStandardDuration as tv_duration,
    LOWER(com.netName) as tv_comapny,
    tv_main.adId as ad_id,
    LOWER(media_type_long) as media_type,
    LOWER(media_type_detail) as media_type_detail,
    LOWER(tv_type_ooh_reg) as type_name,
    LOWER(adDistributionType) as placement_name,
    researchDate as date,
    SUM(ConsolidatedCostRUB_disc) as cost_rub_disc
FROM  media_tv_costs as tv_main
LEFT JOIN adex_company_dict_tv as com ON com.cid = tv_main.cid
LEFT JOIN adex_ad_dict_list_tv as dur ON dur.adId = tv_main.adId
LEFT JOIN adex_regions_dict as region on region.regionId = tv_main.regionId
WHERE researchDate >= '2024-01-01'
GROUP BY
    region.regionName,   
    dur.adStandardDuration,
    com.netName,
    tv_main.adId,
    media_type_long,
    media_type_detail,  
    tv_type_ooh_reg,
    adDistributionType,
    researchDate
'''    

RADIO_SQL = '''
SELECT
    dur.adStandardDuration as ra_duration,
    LOWER(company.companyName) as ra_comapny,
    LOWER(company.netName) as ra_net,
    ra_main.adId as ad_id,
    LOWER(media_type_long) as media_type,
    LOWER(media_type_detail) as media_type_detail,
    LOWER(ra_type.adTypeName) as type_name,
    LOWER(adDistributionType) as placement_name,
    researchDate as date,
    SUM(ConsolidatedCostRUB_disc) as cost_rub_disc
FROM  media_radio_costs as ra_main
LEFT JOIN adex_ad_type_dict_radio as ra_type on ra_type.ad_type_custom = ra_main.ad_type_custom
LEFT JOIN adex_company_dict_radio as company on company.cid = ra_main.cid
LEFT JOIN adex_ad_dict_list_radio as dur ON dur.adId = ra_main.adId
WHERE researchDate >= '2024-01-01'
GROUP BY
    dur.adStandardDuration,
    company.companyName,
    company.netName,
    ra_main.adId,
    media_type_long,
    media_type_detail,
    ra_type.adTypeName,
    adDistributionType,
    researchDate
'''

OOH_SQL = '''
SELECT
    region.regionName as region_ooh,
    adId as ad_id,
    LOWER(media_type_long) as media_type,
    LOWER(media_type_detail) as media_type_detail,
    LOWER(od_type.adTypeName) as type_name,
    LOWER(adDistributionType) as placement_name,
    researchDate as date,
    SUM(ConsolidatedCostRUB_disc) as cost_rub_disc
FROM  media_outdoor_costs as od_main
LEFT JOIN adex_ad_type_dict_outdoor as od_type on od_type.ad_type_custom = od_main.ad_type_custom
LEFT JOIN adex_regions_dict as region on region.regionId = od_main.regionId
WHERE researchDate >= '2024-01-01'
GROUP BY
    region.regionName,
    adId,
    media_type_long,
    media_type_detail,  
    od_type.adTypeName,
    adDistributionType,
    researchDate
'''

PRESS_SQL = '''
SELECT
    LOWER(company.netName) as pr_net,
    adId as ad_id,
    LOWER(media_type_long) as media_type,
    LOWER(media_type_detail) as media_type_detail,
    LOWER(pr_type.adTypeName) as type_name,
    LOWER(adDistributionType) as placement_name,
    researchDate as date,
    SUM(ConsolidatedCostRUB_disc) as cost_rub_disc
FROM  media_press_costs as pr_main
LEFT JOIN adex_ad_type_dict_press as pr_type on pr_type.ad_type_custom = pr_main.ad_type_custom
LEFT JOIN adex_company_dict_press as company on company.cid = pr_main.cid
WHERE researchDate >= '2024-01-01'
GROUP BY
    company.netName,
    adId,
    media_type_long,
    media_type_detail,   
    pr_type.adTypeName,
    adDistributionType,
    researchDate
''' 

OPERCOM_TV_RATE_NAT = """  
                SELECT
                    nts.adID as id,
                    researchDate as date,
                    adDistributionType as ad_placement_id,
                    LOWER(tv_type.adTypeName) as ad_type_name,
                    nts.adStandardDuration as duration,
                    tv_region.regionName,
                    nts.media_type_detail,
                    SUM(RtgPer) as tvr_18,
                    SUM(StandRtgPer) as st_tvr
                FROM nat_tv_simple as nts
                LEFT JOIN tv_index_ad_type_dict as tv_type ON tv_type.adTypeId = nts.adTypeId
                LEFT JOIN tv_index_region_dict as tv_region ON tv_region.regionId = nts.regionId
                WHERE prj_name = 'ALL_18+' AND researchDate >= '2024-01-01' AND researchDate <= '2024-12-31' AND adTypeName = 'ролик' AND (adDistributionType = 'N' or adDistributionType = 'O')
                GROUP BY
                    nts.adID,
                    researchDate,
                    adDistributionType,
                    LOWER(tv_type.adTypeName),
                    nts.adStandardDuration,
                    tv_region.regionName,
                    nts.media_type_detail
UNION
                SELECT
                    nts.adID as id,
                    researchDate as date,
                    adDistributionType as ad_placement_id,
                    LOWER(tv_type.adTypeName) as ad_type_name,
                    nts.adStandardDuration as duration,
                    tv_region.regionName,
                    nts.media_type_detail,
                    SUM(RtgPer) as tvr_18,
                    SUM(StandRtgPer) as st_tvr
                FROM big_tv_simple as nts
                LEFT JOIN tv_index_ad_type_dict as tv_type ON tv_type.adTypeId = nts.adTypeId
                LEFT JOIN tv_index_region_dict as tv_region ON tv_region.regionId = nts.regionId
                WHERE prj_name = 'ALL_18+' AND researchDate >= '2025-01-01' AND (adDistributionType = 'N' or adDistributionType = 'O')
                GROUP BY
                    nts.adID,
                    researchDate,
                    adDistributionType,
                    LOWER(tv_type.adTypeName),
                    nts.adStandardDuration,
                    tv_region.regionName,
                    nts.media_type_detail

"""
OPERCOM_TV_RATE_REG = """  
                SELECT
                    nts.adID as id,
                    researchDate as date,
                    adDistributionType as ad_placement_id,
                    LOWER(tv_type.adTypeName) as ad_type_name,
                    nts.adStandardDuration as duration,
                    tv_region.regionName,
                    nts.media_type_detail,
                    SUM(RtgPer_w) as tvr_18,
                    SUM(RtgPer) as tvr_18_not_weighted,
                    SUM(StandRtgPer) as st_tvr
                FROM reg_tv_simple as nts
                LEFT JOIN tv_index_ad_type_dict as tv_type ON tv_type.adTypeId = nts.adTypeId 
                LEFT JOIN tv_index_region_dict as tv_region ON tv_region.regionId = nts.regionId 
                WHERE prj_name = 'ALL_18+' AND researchDate >= '2024-01-01'
                GROUP BY
                    nts.adID,
                    researchDate,
                    adDistributionType,
                    LOWER(tv_type.adTypeName),
                    nts.adStandardDuration,
                    tv_region.regionName,
                    nts.media_type_detail
 
"""