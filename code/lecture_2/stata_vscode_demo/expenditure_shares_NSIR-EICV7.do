use "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\NSIR_microdata\NISR-EICV7\Cross_Section\CS_S8B_Food_Expenditure_Consumption.dta", clear

desc
keep if province ==1
tab s8bq0
tab pov_jan


forvalues v=2/5{
gen bought_it_v`v'=(s8bq2_v`v'==1) if missing(s8bq2_v`v')==0
replace s8bq4_v`v'=0 if s8bq2_v`v'==2 //fill in expenditure as zero if did not purchase
bysort hhid: egen spent_HHtot_v`v'=total(s8bq4_v`v')
}
egen bought_it_any=rowmax(bought_it_v?)
egen spent_item_any=rowtotal(s8bq4_v?) 
egen spent_HHtot_any=rowtotal(spent_HHtot_v?)
*--make sure that each HH expenditure sums to 1
gen temp_spent_on_any=spent_item_any/spent_HHtot_any
bysort hhid: egen check=total(temp_spent_on_any)
replace check=round(check,0.005)
*br hhid s8bq0 s8bq2_v? s8bq4_v? spent_HHtot_any temp_spent_on_any if check!=1
unique hhid if check!=1
drop if spent_HHtot_any==0 //drop any households that never buy any food item
unique hhid if check!=1
drop check temp_spent_on_any
*--
gen spent_on_any=spent_item_any/spent_HHtot_any
drop spent_item_any spent_HHtot_any


*----report  overall visits----
levelsof s8bq0, local(item_l)
foreach i in `item_l'{
	*share purchased
	qui sum bought_it_any if s8bq0==`i' & pov_jan==1
	local pov_mean: di % 3.2f `r(mean)'
	qui sum bought_it_any if s8bq0==`i'
	local mean: di % 3.2f `r(mean)'
	local mean_dff: di % 3.2f `pov_mean'-`mean'
	*share spent
	qui sum spent_on_any if s8bq0==`i' & pov_jan==1
	local pov_mean_spnt: di % 3.2f `r(mean)'
	qui sum spent_on_any if s8bq0==`i'
	local mean_spnt: di % 3.2f `r(mean)'
	local mean_spnt_dff: di % 3.2f `pov_mean_spnt'-`mean_spnt'
	*display
	local lbl : label (s8bq0) `i'
	local lbl = subinstr("`lbl'", ",", ";", .)
	display "`lbl', `mean', `pov_mean', `mean_dff', `mean_spnt', `pov_mean_spnt',`mean_spnt_dff'"
}



*----report bought it visit by visit----
forvalues v=2/5{
foreach i in `item_l'{
qui sum bought_it_v`v' if s8bq0==`i' & pov_jan==1
local pov_mean: di % 3.2f `r(mean)'
qui sum bought_it_v`v' if s8bq0==`i'
local mean: di % 3.2f `r(mean)'
display "`: label (s8bq0) `i'', `mean', `pov_mean'"
}
display "----------------------------"
display "----------------------------"
display "----------------------------"
display "----------------------------"
}





*Non-food items in last 4 weeks
use "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\admin_data\NISR-EICV7\Cross_Section\CS_S8A2_Expenditure.dta", clear

desc
keep if province ==1
tab s8a2q0 
tab pov_jan


replace s8a2q3=0 if s8a2q2==2 //fill in expenditure as zero if did not purchase
bysort hhid: egen spent_HHtot=total(s8a2q3)

*--make sure that each HH expenditure sums to 1
gen temp_spent_on=s8a2q3/spent_HHtot
bysort hhid: egen check=total(temp_spent_on)
replace check=round(check,0.005)
*br hhid s8a2q2 s8a2q3 spent_HHtot temp_spent_on if check!=1
unique hhid if check!=1
drop if spent_HHtot==0 //drop any households that never buy any item
unique hhid if check!=1
drop check temp_spent_on
*--
gen spent_on=s8a2q3/spent_HHtot



*----report  overall visits----
levelsof s8a2q0, local(item_l)
foreach i in `item_l'{
	*share spent
	qui sum spent_on if s8a2q0==`i' & pov_jan==1
	local pov_mean_spnt: di % 3.2f `r(mean)'
	qui sum spent_on if s8a2q0==`i'
	local mean_spnt: di % 3.2f `r(mean)'
	local mean_spnt_dff: di % 3.2f `pov_mean_spnt'-`mean_spnt'
	*display
	local lbl : label (s8a2q0) `i'
	local lbl = subinstr("`lbl'", ",", ";", .)
	display "`lbl', `mean_spnt', `pov_mean_spnt',`mean_spnt_dff'"
}


*Non-food items in last 7 days
use "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\admin_data\NISR-EICV7\Cross_Section\CS_S8A3_Expenditure.dta", clear

desc
keep if province ==1
tab s8a3q0 
tab pov_jan


replace s8a3q3=0 if s8a3q2==2 //fill in expenditure as zero if did not purchase
bysort hhid: egen spent_HHtot=total(s8a3q3)

*--make sure that each HH expenditure sums to 1
gen temp_spent_on=s8a3q3/spent_HHtot
bysort hhid: egen check=total(temp_spent_on)
replace check=round(check,0.005)
*br hhid s8a3q2 s8a3q3 spent_HHtot temp_spent_on if check!=1
unique hhid if check!=1
drop if spent_HHtot==0 //drop any households that never buy any item
unique hhid if check!=1
drop check temp_spent_on
*--
gen spent_on=s8a3q3/spent_HHtot



*----report  overall visits----
levelsof s8a3q0, local(item_l)
foreach i in `item_l'{
	*share spent
	qui sum spent_on if s8a3q0==`i' & pov_jan==1
	local pov_mean_spnt: di % 3.2f `r(mean)'
	qui sum spent_on if s8a3q0==`i'
	local mean_spnt: di % 3.2f `r(mean)'
	local mean_spnt_dff: di % 3.2f `pov_mean_spnt'-`mean_spnt'
	*display
	local lbl : label (s8a3q0) `i'
	local lbl = subinstr("`lbl'", ",", ";", .)
	display "`lbl', `mean_spnt', `pov_mean_spnt',`mean_spnt_dff'"
}


*Non-food items in last 12 months
use "C:\Users\tanner_regan\Box\data_main\kigali_rehousing\source\admin_data\NISR-EICV7\Cross_Section\CS_S8A1_Expenditure.dta", clear

desc
keep if province ==1
tab s8a1q0 
tab pov_jan


replace s8a1q3=0 if s8a1q2==2 //fill in expenditure as zero if did not purchase
bysort hhid: egen spent_HHtot=total(s8a1q3)

*--make sure that each HH expenditure sums to 1
gen temp_spent_on=s8a1q3/spent_HHtot
bysort hhid: egen check=total(temp_spent_on)
replace check=round(check,0.005)
*br hhid s8a1q2 s8a1q3 spent_HHtot temp_spent_on if check!=1
unique hhid if check!=1
drop if spent_HHtot==0 //drop any households that never buy any item
unique hhid if check!=1
drop check temp_spent_on
*--
gen spent_on=s8a1q3/spent_HHtot



*----report  overall visits----
levelsof s8a1q0, local(item_l)
foreach i in `item_l'{
	*share spent
	qui sum spent_on if s8a1q0==`i' & pov_jan==1
	local pov_mean_spnt: di % 3.2f `r(mean)'
	qui sum spent_on if s8a1q0==`i'
	local mean_spnt: di % 3.2f `r(mean)'
	local mean_spnt_dff: di % 3.2f `pov_mean_spnt'-`mean_spnt'
	*display
	local lbl : label (s8a1q0) `i'
	local lbl = subinstr("`lbl'", ",", ";", .)
	display "`lbl', `mean_spnt', `pov_mean_spnt',`mean_spnt_dff'"
}

