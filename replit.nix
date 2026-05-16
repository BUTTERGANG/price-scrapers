{ pkgs }: {
  deps = [
    pkgs.unpackerr
    pkgs.glib
    pkgs.nss
    pkgs.nspr
    pkgs.atk
    pkgs.at-spi2-atk
    pkgs.at-spi2-core
    pkgs.cups
    pkgs.dbus
    pkgs.expat
    pkgs.libdrm
    pkgs.libxkbcommon
    pkgs.mesa
    pkgs.pango
    pkgs.cairo
    pkgs.alsa-lib
    pkgs.xorg.libX11
    pkgs.xorg.libXcomposite
    pkgs.xorg.libXdamage
    pkgs.xorg.libXext
    pkgs.xorg.libXfixes
    pkgs.xorg.libXrandr
    pkgs.xorg.libxcb
  ];
}
