# SPDX-License-Identifier: MIT
# shellcheck shell=bash disable=SC2207,SC2329
_legion_powerctl_complete() {
    local cur prev cmd opts profiles
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    if (( COMP_CWORD == 1 )); then
        COMPREPLY=( $(compgen -W 'apply configure wizard select list show delete status
            doctor repair enable disable restore-frequency baseline version help' -- "$cur") )
        return
    fi

    case "$prev" in
        --power-profile)     COMPREPLY=( $(compgen -W 'balanced performance power-saver unchanged' -- "$cur") ); return ;;
        --boost)             COMPREPLY=( $(compgen -W 'on off unchanged' -- "$cur") ); return ;;
        --epp)               COMPREPLY=( $(compgen -W 'performance balance_performance balance_power power unchanged' -- "$cur") ); return ;;
        --min-mhz|--max-mhz) COMPREPLY=( $(compgen -W 'stock unchanged' -- "$cur") ); return ;;
    esac

    cmd="${COMP_WORDS[1]}"
    case "$cmd" in
        apply)             opts='--dry-run --boot' ;;
        repair)            opts='--dry-run' ;;
        configure)         opts='--stapm --slow --fast --temp --power-profile --min-mhz
                                 --max-mhz --boost --epp --description --select --apply' ;;
        select)            opts='--apply' ;;
        delete|enable)     opts='--force' ;;
        status)            opts='--json --waybar' ;;
        restore-frequency) opts='--boost' ;;
        baseline)          opts='--capture --show' ;;
        *)                 opts='' ;;
    esac

    if [[ "$cur" != -* ]]; then
        case "$cmd" in
            repair)
                COMPREPLY=( $(compgen -W 'balanced-plus' -- "$cur") )
                return
                ;;
            apply|wizard|select|show|delete)
                profiles="$(legion-powerctl list 2>/dev/null | awk '{print $(NF-1)}')"
                COMPREPLY=( $(compgen -W "$profiles" -- "$cur") )
                return
                ;;
        esac
    fi

    if [[ -n "$opts" ]]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    fi
}
complete -F _legion_powerctl_complete legion-powerctl
