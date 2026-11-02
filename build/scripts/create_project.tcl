# Relative-path project creation. No synthesis or implementation is launched here.
set release_root [file normalize [file join [file dirname [info script]] ../..]]
set work_root [file join $release_root build work system]
if {[llength $argv] > 0} {set work_root [file normalize [lindex $argv 0]]}
if {[file exists [file join $work_root system.xpr]]} {
    error "Project already exists; choose a new output directory."
}
create_project system $work_root -part xc7z020clg400-1
set_property target_language Verilog [current_project]
set_property ip_repo_paths [list [file join $release_root src video ip]] [current_project]
update_ip_catalog
foreach directory [list [file join $release_root src cnn rtl] [file join $release_root src quality_gate rtl] [file join $release_root src video rtl]] {
    foreach pattern {*.v *.sv *.dat} {
        set files [glob -nocomplain -directory $directory $pattern]
        if {[llength $files]} {add_files -norecurse $files}
    }
}
add_files -fileset constrs_1 -norecurse [file join $release_root src system constraints.xdc]
source [file join $release_root src system system_bd.tcl]
validate_bd_design
save_bd_design
set release_bd [get_files */base.bd]
generate_target all $release_bd
make_wrapper -files $release_bd -top
set wrapper [file join $work_root system.gen sources_1 bd base hdl base_wrapper.v]
if {![file exists $wrapper]} {error "Generated wrapper missing: $wrapper"}
add_files -norecurse $wrapper
set_property top base_wrapper [current_fileset]
set_property strategy Performance_ExplorePostRoutePhysOpt [get_runs impl_1]
update_compile_order -fileset sources_1
puts "RELEASE_PROJECT_CREATED $work_root"
