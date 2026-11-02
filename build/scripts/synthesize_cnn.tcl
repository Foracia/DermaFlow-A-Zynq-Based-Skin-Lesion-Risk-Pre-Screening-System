set release_root [file normalize [file join [file dirname [info script]] ../..]]
set project [file join $release_root build work cnn_hls]
open_project $project
set_top grouped_network
add_files [file join $release_root src cnn hls core.cpp] -cflags "-std=c++14 -I[file join $release_root src cnn hls]"
open_solution solution -flow_target vivado
set_part {xc7z020clg400-1}
create_clock -period 12.5 -name default
set_clock_uncertainty 2.7
csynth_design
exit
