"""Math shim: uses mathutils when available (Blender), pure-Python fallback otherwise.

The fallback is NOT optimized — it only needs to be correct for tests.
Inside Blender, the real mathutils is always used.
"""
import math

_use_fallback = False
try:
    from mathutils import Matrix, Vector, Euler
    # Detect if mathutils is mocked (e.g. by pytest conftest)
    if not isinstance(Matrix, type):
        _use_fallback = True
except ImportError:
    _use_fallback = True

if not _use_fallback:
    pass  # Using real mathutils
else:
    # Pure-Python fallback implementations

    class Vector:
        """Minimal Vector (3D or 4D)."""
        __slots__ = ('_data',)

        def __init__(self, data=(0.0, 0.0, 0.0)):
            self._data = list(float(x) for x in data)

        def __len__(self):
            return len(self._data)

        def __getitem__(self, i):
            return self._data[i]

        def __setitem__(self, i, v):
            self._data[i] = float(v)

        def __iter__(self):
            return iter(self._data)

        def __repr__(self):
            return f"Vector({self._data})"

        def __neg__(self):
            return Vector([-x for x in self._data])

        def __add__(self, other):
            return Vector([a + b for a, b in zip(self._data, other)])

        def __sub__(self, other):
            return Vector([a - b for a, b in zip(self._data, other)])

        def __mul__(self, scalar):
            return Vector([x * scalar for x in self._data])

        def __rmul__(self, scalar):
            return self.__mul__(scalar)

        def __truediv__(self, scalar):
            return Vector([x / scalar for x in self._data])

        @property
        def x(self):
            return self._data[0]

        @x.setter
        def x(self, v):
            self._data[0] = float(v)

        @property
        def y(self):
            return self._data[1]

        @y.setter
        def y(self, v):
            self._data[1] = float(v)

        @property
        def z(self):
            return self._data[2]

        @z.setter
        def z(self, v):
            self._data[2] = float(v)

        @property
        def length(self):
            return math.sqrt(sum(x * x for x in self._data))

        def normalize(self):
            l = self.length
            if l > 0:
                self._data = [x / l for x in self._data]

        def normalized(self):
            l = self.length
            if l > 0:
                return Vector([x / l for x in self._data])
            return Vector(self._data)

        def dot(self, other):
            return sum(a * b for a, b in zip(self._data, other))

        def cross(self, other):
            a, b = self._data, list(other)
            return Vector([
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            ])

        def copy(self):
            return Vector(self._data[:])

        def to_tuple(self, precision=-1):
            if precision >= 0:
                return tuple(round(x, precision) for x in self._data)
            return tuple(self._data)

        def resize_2d(self):
            self._data = self._data[:2]

        @property
        def xyz(self):
            return Vector(self._data[:3])


    class Matrix:
        """Minimal 4x4 Matrix (row-major internally)."""
        __slots__ = ('_rows',)

        def __init__(self, rows=None):
            if rows is None:
                self._rows = [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ]
            else:
                self._rows = [list(row) for row in rows]

        def __repr__(self):
            return f"Matrix({self._rows})"

        def __getitem__(self, i):
            return self._rows[i]

        def __setitem__(self, i, v):
            self._rows[i] = list(v)

        def copy(self):
            return Matrix([row[:] for row in self._rows])

        @staticmethod
        def Identity(size=4):
            m = [[0] * size for _ in range(size)]
            for i in range(size):
                m[i][i] = 1.0
            return Matrix(m)

        @staticmethod
        def Translation(vec):
            m = Matrix.Identity(4)
            m[0][3] = vec[0]
            m[1][3] = vec[1]
            m[2][3] = vec[2]
            return m

        @staticmethod
        def Scale(factor, size=4, axis=None):
            if axis is not None:
                # Scale along a specific axis
                ax = Vector(axis).normalized()
                m = Matrix.Identity(size)
                for i in range(3):
                    for j in range(3):
                        if i == j:
                            m[i][j] = 1.0 + (factor - 1.0) * ax[i] * ax[j]
                        else:
                            m[i][j] = (factor - 1.0) * ax[i] * ax[j]
                return m
            m = [[0] * size for _ in range(size)]
            for i in range(size):
                m[i][i] = factor
            if size == 4:
                m[3][3] = 1.0
            return Matrix(m)

        @staticmethod
        def Rotation(angle, size, axis):
            """Rotation matrix. axis can be 'X','Y','Z' or a Vector."""
            c = math.cos(angle)
            s = math.sin(angle)
            if isinstance(axis, str):
                axis = {'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[axis]
            ax = Vector(axis).normalized()
            x, y, z = ax[0], ax[1], ax[2]
            t = 1 - c
            m = Matrix.Identity(size)
            m[0][0] = t * x * x + c
            m[0][1] = t * x * y - s * z
            m[0][2] = t * x * z + s * y
            m[1][0] = t * x * y + s * z
            m[1][1] = t * y * y + c
            m[1][2] = t * y * z - s * x
            m[2][0] = t * x * z - s * y
            m[2][1] = t * y * z + s * x
            m[2][2] = t * z * z + c
            return m

        def __matmul__(self, other):
            if isinstance(other, Matrix):
                n = len(self._rows)
                result = [[0] * n for _ in range(n)]
                for i in range(n):
                    for j in range(n):
                        result[i][j] = sum(self._rows[i][k] * other._rows[k][j] for k in range(n))
                return Matrix(result)
            elif isinstance(other, Vector):
                n = len(self._rows)
                v = list(other)
                if len(v) == 3 and n == 4:
                    v = v + [1.0]
                result = [sum(self._rows[i][j] * v[j] for j in range(n)) for i in range(n)]
                if len(other) == 3 and n == 4:
                    return Vector(result[:3])
                return Vector(result)
            return NotImplemented

        def to_3x3(self):
            return Matrix([row[:3] for row in self._rows[:3]])

        def to_4x4(self):
            if len(self._rows) == 3:
                m = Matrix.Identity(4)
                for i in range(3):
                    for j in range(3):
                        m[i][j] = self._rows[i][j]
                return m
            return self.copy()

        def transposed(self):
            n = len(self._rows)
            return Matrix([[self._rows[j][i] for j in range(n)] for i in range(n)])

        def determinant(self):
            m = self._rows
            if len(m) == 3:
                return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
            # 4x4 via cofactor expansion along first row
            det = 0
            for j in range(4):
                minor = [[m[r][c] for c in range(4) if c != j] for r in range(1, 4)]
                cofactor = ((-1) ** j) * Matrix(minor).determinant()
                det += m[0][j] * cofactor
            return det

        def inverted(self):
            n = len(self._rows)
            # Augmented matrix approach
            aug = [self._rows[i][:] + [1.0 if j == i else 0.0 for j in range(n)] for i in range(n)]
            for col in range(n):
                # Find pivot
                max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
                aug[col], aug[max_row] = aug[max_row], aug[col]
                pivot = aug[col][col]
                if abs(pivot) < 1e-12:
                    raise ValueError("Matrix is not invertible")
                for j in range(2 * n):
                    aug[col][j] /= pivot
                for row in range(n):
                    if row != col:
                        factor = aug[row][col]
                        for j in range(2 * n):
                            aug[row][j] -= factor * aug[col][j]
            return Matrix([aug[i][n:] for i in range(n)])

        def inverted_safe(self):
            try:
                return self.inverted()
            except ValueError:
                return Matrix.Identity(len(self._rows))

        def normalized(self):
            """Normalize the 3x3 rotation part (make each column unit length)."""
            m = self.copy()
            for j in range(3):
                col = Vector([m[i][j] for i in range(3)])
                l = col.length
                if l > 0:
                    for i in range(3):
                        m[i][j] /= l
            return m

        def decompose(self):
            """Decompose into (translation, quaternion, scale)."""
            # Translation
            trans = Vector([self._rows[0][3], self._rows[1][3], self._rows[2][3]])
            # Scale
            sx = Vector([self._rows[0][0], self._rows[1][0], self._rows[2][0]]).length
            sy = Vector([self._rows[0][1], self._rows[1][1], self._rows[2][1]]).length
            sz = Vector([self._rows[0][2], self._rows[1][2], self._rows[2][2]]).length
            scale = Vector([sx, sy, sz])
            # Rotation matrix (normalized)
            rot = [[0] * 3 for _ in range(3)]
            for i in range(3):
                rot[i][0] = self._rows[i][0] / sx if sx > 0 else 0
                rot[i][1] = self._rows[i][1] / sy if sy > 0 else 0
                rot[i][2] = self._rows[i][2] / sz if sz > 0 else 0
            # Quaternion from rotation matrix
            quat = _matrix3_to_quaternion(rot)
            return trans, quat, scale

        def to_euler(self, order='XYZ', compatible=None):
            """Convert rotation part to Euler angles."""
            m = self._rows
            if order == 'XYZ':
                sy = m[0][2]
                sy = max(-1, min(1, sy))
                y = math.asin(sy)
                if abs(sy) < 0.99999:
                    x = math.atan2(-m[1][2], m[2][2])
                    z = math.atan2(-m[0][1], m[0][0])
                else:
                    x = math.atan2(m[2][1], m[1][1])
                    z = 0
                return Euler((x, y, z), order)
            raise NotImplementedError(f"Euler order {order} not implemented")

        @property
        def translation(self):
            return Vector([self._rows[0][3], self._rows[1][3], self._rows[2][3]])

        @property
        def is_negative(self):
            return self.to_3x3().determinant() < 0

        def to_list(self):
            """Return as nested list (for Intermediate Representation serialization)."""
            return [row[:] for row in self._rows]


    class Quaternion:
        """Minimal Quaternion (w, x, y, z)."""
        __slots__ = ('w', 'x', 'y', 'z')

        def __init__(self, values=(1, 0, 0, 0)):
            self.w = float(values[0])
            self.x = float(values[1])
            self.y = float(values[2])
            self.z = float(values[3])

        def __iter__(self):
            return iter((self.w, self.x, self.y, self.z))

        def __repr__(self):
            return f"Quaternion(({self.w}, {self.x}, {self.y}, {self.z}))"

        def to_euler(self, order='XYZ'):
            # Convert quaternion to rotation matrix, then to euler
            m = _quaternion_to_matrix3(self)
            mat = Matrix.Identity(4)
            for i in range(3):
                for j in range(3):
                    mat[i][j] = m[i][j]
            return mat.to_euler(order)


    class Euler:
        """Minimal Euler angles (x, y, z) with order."""
        __slots__ = ('x', 'y', 'z', 'order')

        def __init__(self, values=(0, 0, 0), order='XYZ'):
            self.x = float(values[0])
            self.y = float(values[1])
            self.z = float(values[2])
            self.order = order

        def __iter__(self):
            return iter((self.x, self.y, self.z))

        def __getitem__(self, i):
            return (self.x, self.y, self.z)[i]

        def __repr__(self):
            return f"Euler(({self.x}, {self.y}, {self.z}), '{self.order}')"

        def to_matrix(self):
            """Convert to 3x3 rotation matrix."""
            cx, sx = math.cos(self.x), math.sin(self.x)
            cy, sy = math.cos(self.y), math.sin(self.y)
            cz, sz = math.cos(self.z), math.sin(self.z)
            if self.order == 'XYZ':
                return Matrix([
                    [cy * cz, -cy * sz, sy],
                    [sx * sy * cz + cx * sz, -sx * sy * sz + cx * cz, -sx * cy],
                    [-cx * sy * cz + sx * sz, cx * sy * sz + sx * cz, cx * cy],
                ])
            raise NotImplementedError(f"Euler order {self.order} not implemented")


    def _matrix3_to_quaternion(m):
        """Convert 3x3 rotation matrix to Quaternion."""
        trace = m[0][0] + m[1][1] + m[2][2]
        if trace > 0:
            s = 0.5 / math.sqrt(trace + 1.0)
            w = 0.25 / s
            x = (m[2][1] - m[1][2]) * s
            y = (m[0][2] - m[2][0]) * s
            z = (m[1][0] - m[0][1]) * s
        elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
            s = 2.0 * math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2])
            w = (m[2][1] - m[1][2]) / s
            x = 0.25 * s
            y = (m[0][1] + m[1][0]) / s
            z = (m[0][2] + m[2][0]) / s
        elif m[1][1] > m[2][2]:
            s = 2.0 * math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2])
            w = (m[0][2] - m[2][0]) / s
            x = (m[0][1] + m[1][0]) / s
            y = 0.25 * s
            z = (m[1][2] + m[2][1]) / s
        else:
            s = 2.0 * math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1])
            w = (m[1][0] - m[0][1]) / s
            x = (m[0][2] + m[2][0]) / s
            y = (m[1][2] + m[2][1]) / s
            z = 0.25 * s
        return Quaternion((w, x, y, z))


    def _quaternion_to_matrix3(q):
        """Convert Quaternion to 3x3 rotation matrix."""
        w, x, y, z = q.w, q.x, q.y, q.z
        return [
            [1 - 2*(y*y + z*z), 2*(x*y - w*z),     2*(x*z + w*y)],
            [2*(x*y + w*z),     1 - 2*(x*x + z*z), 2*(y*z - w*x)],
            [2*(x*z - w*y),     2*(y*z + w*x),     1 - 2*(x*x + y*y)],
        ]


# --- Utility functions used by multiple pipeline phases ---

def compile_srt_matrix(scale, rotation, position, parent_scl=None):
    """Build a local SRT matrix matching the HSD Joint convention.

    Composes: Translation @ RotZ @ RotY @ RotX @ ScaleZ @ ScaleY @ ScaleX
    With optional aligned scale inheritance correction for non-uniform parent scales.
    """
    scale_x = Matrix.Scale(scale[0], 4, [1.0, 0.0, 0.0])
    scale_y = Matrix.Scale(scale[1], 4, [0.0, 1.0, 0.0])
    scale_z = Matrix.Scale(scale[2], 4, [0.0, 0.0, 1.0])
    rotation_x = Matrix.Rotation(rotation[0], 4, 'X')
    rotation_y = Matrix.Rotation(rotation[1], 4, 'Y')
    rotation_z = Matrix.Rotation(rotation[2], 4, 'Z')
    translation = Matrix.Translation(Vector(position))
    mtx = translation @ rotation_z @ rotation_y @ rotation_x @ scale_z @ scale_y @ scale_x
    if parent_scl:
        for i in range(3):
            for j in range(3):
                mtx[i][j] *= parent_scl[j] / parent_scl[i]
    return mtx


def matrix_to_list(matrix):
    """Convert a Matrix to list[list[float]] for IR storage."""
    if hasattr(matrix, 'to_list'):
        return matrix.to_list()
    return [[matrix[i][j] for j in range(4)] for i in range(4)]
