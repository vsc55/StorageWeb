"""Un código QR solo con la biblioteca estándar, porque la alternativa era peor.

Dar de alta un segundo factor es llevar un centenar de caracteres de esta pantalla a un móvil. La semilla en
base32 siempre está en la página (es la mitad que alguien puede leer y comprobar), pero nadie la teclea si hay un
cuadrado al que apuntar con la cámara. Añadir una biblioteca para dibujar un cuadrado no compensa, así que esto es
ISO/IEC 18004: **modo byte, corrección de errores L, versiones 1 a 10**. Caben 213 bytes y un enlace
``otpauth://`` ronda los 140; la versión se elige por la longitud, así que se dibuja el cuadrado más pequeño que
cabe. Portado de ServiceSentry (mismo autor).

**Nada es una suposición.** Los tests comprueban la aritmética Reed-Solomon con los codewords que publica la propia
norma para su ejemplo, los bits de formato con su tabla de treinta y dos, y los patrones de localización, sincronía
y alineación con las posiciones que fija. Lo que un test no puede hacer es poner un móvil delante de la pantalla:
por eso el alta nunca se fía solo de esto (la semilla va al lado, y el código que genera la aplicación tiene que
verificar antes de activar el factor).

Nada del usuario llega a la salida: el SVG se construye con enteros (coordenadas de módulos), y el único texto de
entrada es la URI ``otpauth:`` que monta este paquete.
"""
from __future__ import annotations

# Capacidad por versión con corrección L: (codewords de corrección por bloque, ((bloques, datos por bloque), …)).
# Los bloques son lo incómodo del formato: desde la versión 6 los datos se parten, cada bloque lleva su propia
# corrección y luego se INTERCALAN. Tratar la tabla como un único bloque da un símbolo estructuralmente válido que se
# decodifica como basura, el fallo que parece una cámara estropeada.
_EC_L: dict[int, tuple] = {
    1: (7, ((1, 19),)),
    2: (10, ((1, 34),)),
    3: (15, ((1, 55),)),
    4: (20, ((1, 80),)),
    5: (26, ((1, 108),)),
    6: (18, ((2, 68),)),
    7: (20, ((2, 78),)),
    8: (24, ((2, 97),)),
    9: (30, ((2, 116),)),
    10: (18, ((2, 68), (2, 69))),
}

# Dónde van los patrones de alineación por versión: los centros de fila y columna; cada combinación lleva uno salvo
# las tres esquinas que ocupan los patrones de localización.
_ALIGN: dict[int, tuple] = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30),
    6: (6, 34), 7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}

_EC_LEVEL_BITS = 0b01                # nivel L en la información de formato (M=00, L=01, H=10, Q=11)
# La máscara con la que se hace XOR a la información de formato: sin ella, un símbolo con todos los bits de
# formato a cero sería una configuración válida.
_FORMAT_MASK = 0b101010000010010
_FORMAT_POLY = 0b10100110111        # generador BCH(15,5)
_VERSION_POLY = 0b1111100100101     # generador BCH(18,6), versiones 7 y siguientes

_MAX_VERSION = max(_EC_L)


# --------------------------------------------------------------------------- GF(256)
# El cuerpo en el que vive la aritmética del QR: bytes, la suma es XOR y el producto, una tabla de logaritmos sobre
# el polinomio primitivo x⁸+x⁴+x³+x²+1 (0x11D).

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a: int, b: int) -> int:
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list:
    """El polinomio generador para ``degree`` codewords de corrección: ∏(x − α^i)."""
    poly = [1]
    for i in range(degree):
        poly.append(0)
        for j in range(len(poly) - 1, 0, -1):
            poly[j] = poly[j - 1] ^ _gf_mul(poly[j], _EXP[i])
        poly[0] = _gf_mul(poly[0], _EXP[i])
    return poly


def rs_ecc(data: bytes, degree: int) -> bytes:
    """Los ``degree`` codewords de corrección de un bloque (división larga de polinomios).

    Pública porque es la mitad de este fichero que se puede comprobar con algo de fuera: el ejemplo de la norma publica
    los codewords de datos y los que debe devolver para ellos.
    """
    gen = _rs_generator(degree)
    rem = [0] * degree
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(degree):
            rem[i] ^= _gf_mul(gen[degree - 1 - i], factor)
    return bytes(rem)


# --------------------------------------------------------------------------- codificación

class _Bits:
    """Una cadena de bits en construcción. Una lista de 0/1 y no un entero: se lee bit a bit en un orden fijo, y los
    ceros iniciales que perdería un entero son datos."""

    def __init__(self) -> None:
        self.bits: list = []

    def put(self, value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _char_count_bits(version: int) -> int:
    """Modo byte: 8 bits de longitud hasta la versión 9 y 16 desde la 10."""
    return 8 if version < 10 else 16


def capacity(version: int) -> int:
    """Cuántos bytes caben en ``version`` con nivel L."""
    _ec_per_block, groups = _EC_L[version]
    total = sum(count * size for count, size in groups)
    # Cuatro bits del indicador de modo más la longitud, redondeado a bytes enteros.
    return total - 1 - (_char_count_bits(version) // 8)


def best_version(nbytes: int) -> int:
    """La versión más pequeña que admite ``nbytes``, o 0 si ninguna. Cero y no una excepción: la página enseña la
    semilla sin cuadrado en vez de un error 500."""
    for version in range(1, _MAX_VERSION + 1):
        if nbytes <= capacity(version):
            return version
    return 0


def data_codewords(payload: bytes, version: int) -> bytes:
    """Contenido → los codewords de datos de ``version``: modo, longitud, bytes, terminador y relleno."""
    _ec_per_block, groups = _EC_L[version]
    data_total = sum(count * size for count, size in groups)

    bits = _Bits()
    bits.put(0b0100, 4)                                   # modo byte
    bits.put(len(payload), _char_count_bits(version))
    for byte in payload:
        bits.put(byte, 8)
    bits.put(0, min(4, data_total * 8 - len(bits)))       # terminador: hasta cuatro ceros
    bits.put(0, -len(bits) % 8)                           # hasta completar el byte
    data = bytearray(int("".join(str(b) for b in bits.bits[i:i + 8]), 2) for i in range(0, len(bits), 8))
    for i in range(data_total - len(data)):               # los dos codewords de relleno de la norma, alternos
        data.append(0xEC if i % 2 == 0 else 0x11)
    return bytes(data)


def _interleave(data: bytes, version: int) -> bytes:
    """Los datos partidos en bloques, cada uno con su corrección, e intercalados: el primer codeword de cada bloque,
    luego el segundo… y la corrección detrás, igual. Así un daño seguido se reparte entre bloques."""
    ec_per_block, groups = _EC_L[version]
    blocks, eccs, pos = [], [], 0
    for count, size in groups:
        for _ in range(count):
            block = bytes(data[pos:pos + size])
            pos += size
            blocks.append(block)
            eccs.append(rs_ecc(block, ec_per_block))
    out = bytearray()
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_per_block):
        for ecc in eccs:
            out.append(ecc[i])
    return bytes(out)


# --------------------------------------------------------------------------- el símbolo

def _bch_remainder(value: int, poly: int, data_bits: int) -> int:
    """``value`` desplazado el grado del generador, módulo ``poly``."""
    degree = poly.bit_length() - 1
    rem = value << degree
    for shift in range(data_bits - 1, -1, -1):
        if rem & (1 << (shift + degree)):
            rem ^= poly << shift
    return rem


def format_bits(mask: int) -> int:
    """Los quince bits de formato para el nivel L y ``mask``, con la máscara de la norma."""
    value = (_EC_LEVEL_BITS << 3) | (mask & 0b111)
    return ((value << 10) | _bch_remainder(value, _FORMAT_POLY, 5)) ^ _FORMAT_MASK


def version_bits(version: int) -> int:
    """Los dieciocho bits de versión (solo desde la versión 7)."""
    return (version << 12) | _bch_remainder(version, _VERSION_POLY, 6)


def _blank(size: int) -> tuple:
    return ([[False] * size for _ in range(size)],
            [[False] * size for _ in range(size)])   # módulos y reservados


def _place_function_patterns(mod: list, res: list, version: int) -> None:
    size = len(mod)

    def square(top: int, left: int, dim: int, fn) -> None:
        for r in range(dim):
            for c in range(dim):
                rr, cc = top + r, left + c
                if 0 <= rr < size and 0 <= cc < size:
                    mod[rr][cc] = fn(r, c)
                    res[rr][cc] = True

    # Patrones de localización y su separador, en las tres esquinas que no son la inferior derecha: el anillo de 7×7,
    # un hueco y el núcleo de 3×3.
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        square(top, left, 7, lambda r, c: r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4))
        for r in range(-1, 8):                # el separador claro de un módulo alrededor
            for c in range(-1, 8):
                rr, cc = top + r, left + c
                if 0 <= rr < size and 0 <= cc < size and not res[rr][cc]:
                    mod[rr][cc] = False
                    res[rr][cc] = True

    # Patrones de sincronía: la fila y la columna alternas que fijan el paso de los módulos.
    for i in range(size):
        for rr, cc in ((6, i), (i, 6)):
            if not res[rr][cc]:
                mod[rr][cc] = (i % 2 == 0)
                res[rr][cc] = True

    # Patrones de alineación, en cada combinación de centros salvo las que caerían sobre un localizador.
    centres = _ALIGN[version]
    for row in centres:
        for col in centres:
            if (row, col) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    mod[row + r][col + c] = max(abs(r), abs(c)) != 1
                    res[row + r][col + c] = True

    mod[size - 8][8] = True                   # el módulo oscuro fijo
    res[size - 8][8] = True

    # Reserva las zonas de formato (se escriben después de elegir la máscara).
    for i in range(9):
        res[8][i] = True
        res[i][8] = True
    for i in range(8):
        res[8][size - 1 - i] = True
        res[size - 1 - i][8] = True

    if version >= 7:                          # y los bloques de versión
        for i in range(18):
            r, c = i // 3, i % 3
            res[size - 11 + c][r] = True
            res[r][size - 11 + c] = True


def _write_version(mod: list, version: int) -> None:
    if version < 7:
        return
    size = len(mod)
    bits = version_bits(version)
    for i in range(18):
        bit = bool((bits >> i) & 1)
        r, c = i // 3, i % 3
        mod[size - 11 + c][r] = bit
        mod[r][size - 11 + c] = bit


def _write_format(mod: list, mask: int) -> None:
    size = len(mod)
    bits = format_bits(mask)

    def bit(i: int) -> bool:
        return bool((bits >> i) & 1)

    # La copia junto al localizador de arriba a la izquierda, partida por la fila y la columna de sincronía: los bits
    # 0–5 van por la fila 8, saltan la columna 6 y suben por la columna 8.
    for i in range(6):
        mod[8][i] = bit(i)
    mod[8][7] = bit(6)
    mod[8][8] = bit(7)
    mod[7][8] = bit(8)
    for i in range(9, 15):
        mod[14 - i][8] = bit(i)
    # La segunda copia, para que el formato sobreviva a perder una esquina.
    for i in range(8):
        mod[8][size - 1 - i] = bit(i)
    for i in range(8, 15):
        mod[size - 15 + i][8] = bit(i)


def _mask_at(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _place_data(mod: list, res: list, data: bytes, mask: int) -> None:
    """El contenido, subiendo y bajando de dos en dos columnas desde abajo a la derecha, con la máscara."""
    size = len(mod)
    bits = [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]
    idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:                          # la columna de sincronía no lleva datos
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if res[row][c]:
                    continue
                bit = bool(bits[idx]) if idx < len(bits) else False
                idx += 1
                mod[row][c] = bit != _mask_at(mask, row, c)
        col -= 2
        upward = not upward


def _penalty(mod: list) -> int:
    """Lo mal que se lee un símbolo con máscara, por las cuatro reglas de la norma. Gana la puntuación más baja: un
    símbolo con una gran zona en blanco, o con algo que parece un localizador, confunde a la cámara."""
    size = len(mod)
    score = 0
    lines = [mod[r] for r in range(size)] + [[mod[r][c] for r in range(size)] for c in range(size)]

    for line in lines:                        # regla 1: rachas de cinco o más del mismo color
        run, prev = 1, line[0]
        for value in line[1:]:
            if value == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, value
        if run >= 5:
            score += 3 + (run - 5)

    for r in range(size - 1):                 # regla 2: cada bloque de 2×2 de un color
        for c in range(size - 1):
            if mod[r][c] == mod[r][c + 1] == mod[r + 1][c] == mod[r + 1][c + 1]:
                score += 3

    pattern_a = [True, False, True, True, True, False, True, False, False, False, False]
    pattern_b = list(reversed(pattern_a))
    for line in lines:                        # regla 3: la secuencia 1:1:3:1:1 con cuatro claros al lado
        for i in range(size - 10):
            window = line[i:i + 11]
            if window in (pattern_a, pattern_b):
                score += 40

    dark = sum(1 for row in mod for value in row if value)   # regla 4: lejos de la mitad de oscuros
    score += 10 * (abs(dark * 100 // (size * size) - 50) // 5)
    return score


def matrix(text: str) -> list:
    """``text`` como lista de filas de booleanos (True = módulo oscuro), o vacía si no cabe en una versión 10."""
    payload = str(text or "").encode("utf-8")
    version = best_version(len(payload))
    if not version:
        return []
    size = version * 4 + 17
    data = _interleave(data_codewords(payload, version), version)

    best, best_score = None, None
    for mask in range(8):
        mod, res = _blank(size)
        _place_function_patterns(mod, res, version)
        _write_version(mod, version)
        _place_data(mod, res, data, mask)
        _write_format(mod, mask)
        score = _penalty(mod)
        if best_score is None or score < best_score:
            best, best_score = mod, score
    return best


def svg(text: str, *, quiet: int = 4) -> str:
    """El símbolo como elemento SVG, o ``""`` si no hay nada que dibujar.

    Solo con enteros (las coordenadas de los módulos oscuros): nada de ``text`` llega a la salida, y por eso se puede
    meter en la página tal cual. Sin ``style`` (la CSP no lo permite): colores con ``fill``. ``viewBox`` en módulos y
    sin ancho ni alto, para que el tamaño lo decida el CSS. Cuatro módulos de margen porque la norma dice cuatro.
    """
    mod = matrix(text)
    if not mod:
        return ""
    size = len(mod)
    total = size + quiet * 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" shape-rendering="crispEdges" '
             f'role="img">', f'<rect width="{total}" height="{total}" fill="#fff"/>']
    # Un solo path de rectángulos y no un elemento por módulo: una versión 10 son 3.249 módulos.
    runs = []
    for r, row in enumerate(mod):
        c = 0
        while c < size:
            if row[c]:
                start = c
                while c < size and row[c]:
                    c += 1
                runs.append(f"M{start + quiet} {r + quiet}h{c - start}v1h-{c - start}z")
            else:
                c += 1
    parts.append(f'<path fill="#000" d="{"".join(runs)}"/>')
    parts.append("</svg>")
    return "".join(parts)
