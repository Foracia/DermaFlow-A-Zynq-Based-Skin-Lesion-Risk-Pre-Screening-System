# Create a fresh project and write outputs outside the preserved board payload.
source [file join [file dirname [info script]] create_project.tcl]
set output [file join $release_root build output]
file mkdir $output
launch_runs synth_1 -jobs 1
wait_on_run synth_1
if {![string match {*Complete*} [get_property STATUS [get_runs synth_1]]]} {error "Synthesis did not complete"}
launch_runs impl_1 -to_step {phys_opt_design (Post-Route)} -jobs 1
wait_on_run impl_1
set run_dir [get_property DIRECTORY [get_runs impl_1]]
if {![file exists [file join $run_dir .post_route_phys_opt_design.end.rst]]} {error "Implementation did not complete"}
open_run impl_1
report_utilization -file [file join $output utilization.rpt]
report_utilization -hierarchical -file [file join $output hierarchy.rpt]
report_timing_summary -delay_type min_max -check_timing_verbose -report_unconstrained -file [file join $output timing.rpt]
report_route_status -file [file join $output routing.rpt]
report_drc -file [file join $output drc.rpt]
report_cdc -file [file join $output cdc.rpt]
set setup [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set hold [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]
if {$setup < 0 || $hold < 0 || $errors != 0} {error "Timing or DRC failed; no bitstream is emitted"}
write_bitstream -force [file join $output system.bit]
set handoff [file join $work_root system.gen sources_1 bd base hw_handoff base.hwh]
if {![file exists $handoff]} {error "HWH missing"}
file copy -force $handoff [file join $output system.hwh]
puts "RELEASE_BUILD_OUTPUT $output"
close_project
exit 0
