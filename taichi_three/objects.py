import taichi as ti
import taichi_glsl as ts
from .common import EPS, INF


@ti.data_oriented
class Object:
    def make_one(self, scene):
        raise NotImplementedError


@ti.data_oriented
class ObjectRT(Object):
    @ti.func
    def calc_sdf(self, p):
        ret = INF
        for I in ti.grouped(ti.ndrange(*self.pos.shape())):
            ret = min(ret, self.make_one(I).do_calc_sdf(p))
        return ret

    @ti.func
    def intersect(self, orig, dir):
        ret, normal = INF, ts.vec3(0.0)
        for I in ti.grouped(ti.ndrange(*self.pos.shape())):
            t, n = self.make_one(I).do_intersect(orig, dir)
            if t < ret:
                ret, normal = t, n
        return ret, normal

    def do_calc_sdf(self, p):
        raise NotImplementedError

    def do_intersect(self, orig, dir):
        raise NotImplementedError


@ti.data_oriented
class Ball(ObjectRT):
    def __init__(self, pos, radius):
        self.pos = pos
        self.radius = radius

    @ti.func
    def make_one(self, I):
        return Ball(self.pos[I], self.radius[I])

    @ti.func
    def do_calc_sdf(self, p):
        return ts.distance(self.pos, p) - self.radius

    @ti.func
    def do_intersect(self, orig, dir):
        op = self.pos - orig
        b = op.dot(dir)
        det = b ** 2 - op.norm_sqr() + self.radius ** 2
        ret = INF
        if det > 0.0:
            det = ti.sqrt(det)
            t = b - det
            if t > EPS:
                ret = t
            else:
                t = b + det
                if t > EPS:
                    ret = t
        return ret, ts.normalize(dir * ret - op)


@ti.data_oriented
class ObjectGE(Object):
    @ti.func
    def render(self, scene):
        for I in ti.grouped(ti.ndrange(*self.a.shape())):
            self.make_one(I).do_render(scene)

    @ti.func
    def render_stroke(self, scene):
        for I in ti.grouped(ti.ndrange(*self.a.shape())):
            self.make_one(I).do_render_stroke(scene)

    def do_render(self, scene):
        raise NotImplementedError

    def do_render_stroke(self, scene):
        raise NotImplementedError


@ti.data_oriented
class Line(ObjectGE):
    def __init__(self, a, b):
        self.a = a
        self.b = b

    @ti.func
    def make_one(self, I):
        return Line(self.a[I], self.b[I])

    @ti.func
    def do_render(self, scene):
        W = 1
        A = scene.uncook_coor(scene.camera.untrans_pos(self.a))
        B = scene.uncook_coor(scene.camera.untrans_pos(self.b))
        M, N = int(ti.floor(min(A, B) - W)), int(ti.ceil(max(A, B) + W))
        for X in ti.grouped(ti.ndrange((M.x, N.x), (M.y, N.y))):
            P = B - A
            udf = (ts.cross(X, P) + ts.cross(B, A))**2 / P.norm_sqr()
            XoP = ts.dot(X, P)
            AoB = ts.dot(A, B)
            if XoP > B.norm_sqr() - AoB:
                udf = (B - X).norm_sqr()
            elif XoP < AoB - A.norm_sqr():
                    udf = (A - X).norm_sqr()
            if udf < 0:
                scene.img[X] = ts.vec3(1.0)
            elif udf < W**2:
                t = ts.smoothstep(udf, 0, W**2)
                ti.atomic_min(scene.img[X], ts.vec3(t))


@ti.data_oriented
class Triangle(ObjectGE):
    def __init__(self, a, b, c):
        self.a = a
        self.b = b
        self.c = c

    @ti.func
    def make_one(self, I):
        return Triangle(self.a[I], self.b[I], self.c[I])

    def to_lines(self):
        return Line(self.b, self.c), Line(self.c, self.a), Line(self.a, self.b)

    @ti.func
    def do_render_stroke(self, scene):
        A, B, C = self.to_lines()
        A.do_render(scene)
        B.do_render(scene)
        C.do_render(scene)

    @ti.func
    def do_render(self, scene):
        a = scene.camera.untrans_pos(self.a)
        b = scene.camera.untrans_pos(self.b)
        c = scene.camera.untrans_pos(self.c)
        A = scene.uncook_coor(a)
        B = scene.uncook_coor(b)
        C = scene.uncook_coor(c)
        B_A = B - A
        C_B = C - B
        A_C = A - C
        ilB_A = 1 / ts.length(B_A)
        ilC_B = 1 / ts.length(C_B)
        ilA_C = 1 / ts.length(A_C)
        B_A *= ilB_A
        C_B *= ilC_B
        A_C *= ilA_C
        BxA = ts.cross(B, A) * ilB_A
        CxB = ts.cross(C, B) * ilC_B
        AxC = ts.cross(A, C) * ilA_C
        normal = ts.normalize(ts.cross(a - c, a - b))
        light_dir = scene.camera.untrans_dir(scene.light_dir[None])
        pos = (a + b + c) * (1 / 3)
        dir = ts.vec3(0.0)
        color = scene.opt.render_func(pos, normal, dir, light_dir)
        color = scene.opt.pre_process(color)

        W = 0.4
        M, N = int(ti.floor(min(A, B, C) - W)), int(ti.ceil(max(A, B, C) + W))
        for X in ti.grouped(ti.ndrange((M.x, N.x), (M.y, N.y))):
            AB = ts.cross(X, B_A) + BxA
            BC = ts.cross(X, C_B) + CxB
            CA = ts.cross(X, A_C) + AxC
            udf = max(AB, BC, CA)
            if udf < 0:
                scene.img[X] = color
            elif udf < W:
                t = ts.smoothstep(udf, W, 0)
                ti.atomic_max(scene.img[X], t * color)
