# SPDX-License-Identifier: MIT

function __legion_powerctl_profiles
    command legion-powerctl list 2>/dev/null | awk '{print $(NF-1)}'
end

complete -c legion-powerctl -f
complete -c legion-powerctl -n '__fish_use_subcommand' -a apply -d 'Apply a profile'
complete -c legion-powerctl -n '__fish_use_subcommand' -a configure -d 'Create or update a profile'
complete -c legion-powerctl -n '__fish_use_subcommand' -a wizard -d 'Interactive profile editor'
complete -c legion-powerctl -n '__fish_use_subcommand' -a select -d 'Select the boot profile'
complete -c legion-powerctl -n '__fish_use_subcommand' -a list -d 'List profiles'
complete -c legion-powerctl -n '__fish_use_subcommand' -a show -d 'Show a profile'
complete -c legion-powerctl -n '__fish_use_subcommand' -a delete -d 'Delete a profile'
complete -c legion-powerctl -n '__fish_use_subcommand' -a status -d 'Show configuration and service state'
complete -c legion-powerctl -n '__fish_use_subcommand' -a doctor -d 'Run compatibility checks'
complete -c legion-powerctl -n '__fish_use_subcommand' -a repair -d 'Back up and recover balanced-plus at 78 C'
complete -c legion-powerctl -n '__fish_use_subcommand' -a enable -d 'Enable the boot service'
complete -c legion-powerctl -n '__fish_use_subcommand' -a disable -d 'Disable the boot service'
complete -c legion-powerctl -n '__fish_use_subcommand' -a restore-frequency -d 'Restore stock CPUFreq boundaries'
complete -c legion-powerctl -n '__fish_use_subcommand' -a baseline -d 'Record or show the firmware SMU limits'
complete -c legion-powerctl -n '__fish_use_subcommand' -a version -d 'Show version'
complete -c legion-powerctl -n '__fish_use_subcommand' -a help -d 'Show help'

complete -c legion-powerctl -n '__fish_seen_subcommand_from apply select show delete wizard' -a '(__legion_powerctl_profiles)'
complete -c legion-powerctl -n '__fish_seen_subcommand_from apply' -l dry-run -d 'Print changes without applying them'
complete -c legion-powerctl -n '__fish_seen_subcommand_from repair' -a balanced-plus
complete -c legion-powerctl -n '__fish_seen_subcommand_from repair' -l dry-run -d 'Preview recovery without changing settings'
complete -c legion-powerctl -n '__fish_seen_subcommand_from apply' -l boot -d 'Boot-time apply (used by the systemd unit)'
complete -c legion-powerctl -n '__fish_seen_subcommand_from select' -l apply -d 'Apply immediately'
complete -c legion-powerctl -n '__fish_seen_subcommand_from delete' -l force -d 'Delete even when selected'
complete -c legion-powerctl -n '__fish_seen_subcommand_from restore-frequency' -l boost -xa 'on off unchanged'
complete -c legion-powerctl -n '__fish_seen_subcommand_from baseline' -l capture -d 'Record the firmware limits, once'
complete -c legion-powerctl -n '__fish_seen_subcommand_from baseline' -l show -d 'Print the recorded firmware limits'
complete -c legion-powerctl -n '__fish_seen_subcommand_from enable' -l force -d 'Skip the doctor gate'
complete -c legion-powerctl -n '__fish_seen_subcommand_from status' -l json -d 'Machine-readable status (schema-versioned)'
complete -c legion-powerctl -n '__fish_seen_subcommand_from status' -l waybar -d 'Waybar custom module JSON'

complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l stapm -x -d 'Sustained watts'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l slow -x -d 'Slow PPT watts'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l fast -x -d 'Fast PPT watts'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l temp -x -d 'Temperature ceiling C'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l power-profile -xa 'balanced performance power-saver unchanged'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l min-mhz -x
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l max-mhz -x
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l boost -xa 'on off unchanged'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l epp -xa 'performance balance_performance balance_power power unchanged'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l description -x
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l select -d 'Select for boot'
complete -c legion-powerctl -n '__fish_seen_subcommand_from configure' -l apply -d 'Apply immediately'
