from flaza.app import main
from flaza.core.extensions.patch import apply_patches

if __name__ == "__main__":
    apply_patches()
    main()
