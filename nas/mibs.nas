# interface functions -----------------------------------------------------------------------------

var vert_factor = 1;
var up = func(dir) {
    if (!dir)
        return vert_factor = 1;
    var alt = "position/altitude-ft";
    setprop(alt, getprop(alt) + 0.15 * vert_factor * dir);
    vert_factor += 0.50;
}
