# Compile and simulate the packaged CNN testbench in an isolated work directory.
set release_root [file normalize [file join [file dirname [info script]] ../..]]
set work [file join $release_root build work rtl]
file mkdir $work
cd $work
foreach path [glob -nocomplain -directory [file join $release_root src cnn rtl] *.dat] {
    file copy -force $path [file join $work [file tail $path]]
}
foreach name {input.hex expected.hex} {
    file copy -force [file join $release_root sim cnn $name] [file join $work $name]
}
set verilog [glob -nocomplain -directory [file join $release_root src cnn rtl] *.v]
set systemverilog [glob -nocomplain -directory [file join $release_root src cnn rtl] *.sv]
lappend systemverilog [file join $release_root sim cnn real_core_tb.sv]
if {[llength $verilog]} {exec xvlog {*}$verilog > compile.log 2>@1}
exec xvlog -sv {*}$systemverilog >> compile.log 2>@1
exec xelab real_core_tb -L unisims_ver -L xpm -s cnn_test > elaborate.log 2>@1
exec xsim cnn_test -runall -log simulate.log > runner.log 2>@1
puts "SIMULATION_OUTPUT $work"
exit
