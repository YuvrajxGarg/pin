import os
import sys


def run():
    # A windowed build (no console) has no stdout/stderr; give the CLI somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        from .cli import main

        sys.exit(main())
    # macOS passes -psn_... when launched from Finder on old systems; that's not a command.
    from .webapp import main

    main()


if __name__ == "__main__":
    run()
