import pygame
import requests
import sys
import os
from io import BytesIO
from math import pi, sin, atan2, sqrt, cos, radians
from PyQt5.QtWidgets import QWidget, QInputDialog, QMainWindow, QApplication, QFileDialog
import csv
from PIL import Image, ImageDraw, ImageFont
import xml.etree.ElementTree as ET

LAT_STEP = 0.0035  # Шаги при движении карты по широте и долготе
LON_STEP = 0.007


# Найти объект по координатам
def reverse_geocode(ll):
    geocoder_request_template = "http://geocode-maps.yandex.ru/1.x/?apikey=" \
                                "40d1649f-0493-4b70-98ba-98533de7710b&geocode={ll}&format=json"

    # Выполняем запрос к геокодеру, анализируем ответ
    geocoder_request = geocoder_request_template.format(**locals())
    response = requests.get(geocoder_request)

    if not response:
        raise RuntimeError("""Ошибка выполнения запроса: {request} Http статус: {status} ({reason})""".format(
                request=geocoder_request, status=response.status_code, reason=response.reason))

    # Преобразуем ответ в json-объект
    json_response = response.json()
    # pprint.pprint(json_response)

    # Получаем первый топоним из ответа геокодера
    features = json_response["response"]["GeoObjectCollection"]["featureMember"]
    return features[0]["GeoObject"] if features else None


def ll(x, y):
    return f"{x},{y}"


class SearchResult:
    def __init__(self, point, address):
        self.point = point
        self.address = address


class Map:
    def __init__(self):
        self.lat = None  # координаты центра всей карты
        self.lon = None
        self.zoom = 15
        self.type = "map"
        self.search_result = None
        self.lonlat4 = [(None, None)] * 4  # координаты центров 4-х частей

    def lonlat(self):
        return ll(self.lon, self.lat)

    def correct_lon(self):
        if self.lon > 180:
            self.lon -= 360
        if self.lon < -180:
            self.lon += 360

    def map_size(self):
        # размеры куска карты (600х450 px) в градусах долготы и широты (важна широта)
        dlon = 0.02575 * (2 ** (15 - self.zoom))  # как под 600 pixels
        dlat = cos(radians(self.lat)) * 0.01933 * (2 ** (15 - self.zoom))
        # плотность: по горизонтали dlon/600, по вертикали dlat/450
        return dlon, dlat

    # Обновление параметров карты по нажатой клавише
    def update(self, key_code):
        if key_code == pygame.K_PAGEUP and self.zoom < 19:
            self.zoom += 1
        elif key_code == pygame.K_PAGEDOWN and self.zoom > 5:
            self.zoom -= 1
        elif key_code == pygame.K_LEFT:
            d_lon = LON_STEP * (2 ** (15 - self.zoom))
            if BigStep:
                d_lon *= 4
            self.lon -= d_lon
            self.correct_lon()
        elif key_code == pygame.K_RIGHT:
            d_lon = LON_STEP * (2 ** (15 - self.zoom))
            if BigStep:
                d_lon *= 4
            self.lon += d_lon
            self.correct_lon()
        elif key_code == pygame.K_UP and self.lat < 75:
            d_lat = LAT_STEP * (2 ** (15 - self.zoom))
            if BigStep:
                d_lat *= 4
            self.lat += d_lat
        elif key_code == pygame.K_DOWN and self.lat > -40:
            d_lat = LAT_STEP * (2 ** (15 - self.zoom))
            if BigStep:
                d_lat *= 4
            self.lat -= d_lat
        elif key_code == 127:  # DELETE
            self.search_result = None
        load_4picture(self)

    # Преобразование экранных координат в географические (x,y -> lon,lat)
    def screen_to_geo(self, pos):
        lon0, lat0 = self.lon, self.lat
        x, y = pos
        if x < 540:
            q = 0 if y < 450 else 1
        else:
            q = 2 if y < 450 else 3
        self.lon = self.lonlat4[q][0]
        self.lat = self.lonlat4[q][1]
        dlon, dlat = self.map_size()
        dx = x - 300 if q in (0, 2) else x - 840
        dy = 225 - y if q < 2 else 675 - y
        lon = self.lon + dx * dlon / 600
        lat = self.lat + dy * dlat / 450
        self.lon, self.lat = lon0, lat0
        return lon, lat

    # Преобразование географических координат в экранные  (lon,lat -> x,y)
    def geo_to_screen(self, lon, lat):
        # важно только это верхняя или нижняя часть
        lon0, lat0 = self.lon, self.lat  # запомним главный центр
        dy = 225
        self.lon = self.lonlat4[0][0]
        self.lat = self.lonlat4[0][1]
        dlon, dlat = self.map_size()
        if lat > self.lat + dlat / 2:
            dy = 675
            self.lon = self.lonlat4[2][0]
            self.lat = self.lonlat4[2][1]
            dlon, dlat = self.map_size()
        x = (lon - self.lon) * 600 / dlon + 300
        y = (self.lat - lat) * 450 / dlat + dy
        self.lon, self.lat = lon0, lat0  # вернём центр на место
        return round(x), round(y)

    def add_reverse_toponym_search(self, pos):
        point = self.screen_to_geo(pos)
        x, y = self.geo_to_screen(point[0], point[1])
        toponym = reverse_geocode(ll(point[0], point[1]))
        p = (point[1], point[0])
        self.search_result = SearchResult(p,
                                          toponym["metaDataProperty"]["GeocoderMetaData"]["text"] if toponym else None)
    # ----------------- end <Map> ---------


# Создание карты с параметрами <mp>
def load_map(mp):
    ll = mp.lonlat()
    map_request = f"http://static-maps.yandex.ru/1.x/?ll={ll}&z={mp.zoom}&l={mp.type}"

    if mp.search_result:
        map_request += "&pt={0},{1},pm2grm".format(mp.search_result.point[0],
                                                   mp.search_result.point[1])
    response = requests.get(map_request)
    if not response:
        print("Ошибка выполнения запроса:")
        print(map_request)
        print("Http статус:", response.status_code, "(", response.reason, ")")
        sys.exit(1)
    return response.content


# загрузка карты из Интернета
def load_picture(mp, x, y):
    img = load_map(mp)
    im = pygame.image.load(BytesIO(img))
    screen.blit(im, (x, y))


# загрузка и соединение 4-х частей карты
def load_4picture(mp):
    lat_top_corr = [0.4, 0.1, 0.025, 0.005, 0.0018, 0.0005]
    lat, lon = mp.lat, mp.lon  # запомнить главный центр
    dlon, dlat = mp.map_size()
    mp.lat = lat + dlat / 2  # верхняя половина карты
    if mp.zoom in range(5, 11):
        mp.lat -= lat_top_corr[mp.zoom - 5]  # иногда немного приподнять вверх
    mp.lon = lon - dlon * 0.4  # чтобы по ширине было 90% - убрать "Яндекс"
    dlon *= 0.9
    mp.correct_lon()
    load_picture(mp, 0, 0)
    mp.lonlat4[0] = mp.lon, mp.lat
    mp.lon += dlon
    mp.correct_lon()
    load_picture(mp, 540, 0)
    mp.lonlat4[1] = mp.lon, mp.lat
    mp.lat -= dlat
    mp.lon -= dlon
    mp.correct_lon()
    load_picture(mp, 0, 450)
    mp.lonlat4[2] = mp.lon, mp.lat
    mp.lon += dlon
    mp.correct_lon()
    load_picture(mp, 540, 450)
    mp.lonlat4[3] = mp.lon, mp.lat
    mp.lat, mp.lon = lat, lon  # вернуть главный центр
    if mp.search_result:
        # Если указали мышкой на точку, то печатаем адрес
        font = pygame.font.Font(None, 30)
        text = font.render(mp.search_result.address, 1, (0, 128, 0))
        screen.blit(text, (20, 860))
    mp.search_result = None  # потом надпись удалится
    if route:
        # маршрут есть - рисуем его
        x0, y0 = mp.geo_to_screen(route.lon[0], route.lat[0])
        route.sprite_start.rect.x = x0 - 12
        route.sprite_start.rect.y = y0 - 12
        for i in range(1, len(route.lon)):
            x1, y1 = mp.geo_to_screen(route.lon[i], route.lat[i])
            good0 = (0 <= x0 <= 1080) and (0 <= y0 <= 900)
            good1 = (0 <= x1 <= 1080) and (0 <= y1 <= 900)
            if good0 or good1:
                route.pos[i] = (x1, y1)
                route.pos[i - 1] = (x0, y0)
                pygame.draw.line(screen, (0, 160, 96), (x0, y0), (x1, y1), 5)
                if i % 5 == 0:
                    pygame.draw.circle(screen, (255, 0, 0), (x0, y0), 2)
                    pygame.draw.circle(screen, (255, 255, 0), (x0, y0), 3, 1)
            else:
                route.pos[i] = (None, None)
                route.pos[i - 1] = (None, None)
            x0, y0 = x1, y1
        route.sprite_finish.rect.x = x1 - 12
        route.sprite_finish.rect.y = y1 - 12

    pygame.draw.line(screen, (0, 0, 160), (0, 449), (1199, 449), 1)
    pygame.draw.line(screen, (0, 0, 160), (540, 0), (540, 899), 1)
    pygame.draw.rect(screen, (224, 200, 80), ((1080, 0), (120, 900)))
    pygame.draw.rect(screen, (80, 104, 128), ((1083, 3), (114, 894)))
    print_txt(mp)  # печать всей текстовой информации на правом боку
    all_sprites.draw(screen)
    pygame.display.flip()


def load_sprite(x, y, fname, alpha=False):
    # загрузка картинки из файла
    fullname = os.path.join('Images', fname)
    if not os.path.isfile(fullname):
        print(f"Файл с изображением '{fullname}' не найден")
        return None
    image = pygame.image.load(fullname)
    if alpha:
        image = image.convert()
        colorkey = image.get_at((0, 0))
        image.set_colorkey(colorkey)
    sprite = pygame.sprite.Sprite()
    sprite.image = image
    sprite.rect = sprite.image.get_rect()
    sprite.rect.x, sprite.rect.y = x, y
    return sprite


# печать строки на экран
def write_text(text, size, color, x, y):
    font = pygame.font.Font('fonts/arial.ttf', size)
    text = font.render(text, 1, color)
    screen.blit(text, (x, y))


#  поиск координат по адресу
def adres_coord(adres):
    # global toponym_longitude, toponym_lattitude
    geocoder_api_server = "http://geocode-maps.yandex.ru/1.x/"
    geocoder_params = {
        "apikey": "40d1649f-0493-4b70-98ba-98533de7710b",
        "geocode": adres,
        "format": "json"}
    response = requests.get(geocoder_api_server, params=geocoder_params)
    if not response:
        return None
    json_response = response.json()
    toponym = json_response["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
    toponym_coordinates = toponym["Point"]["pos"]
    lon, lat = toponym_coordinates.split()
    return float(lon), float(lat)


class Button:
    def __init__(self, x, y, name0, name1):
        self.x = x
        self.y = y
        self.active = False
        self.sprites = [None, None]  # неактивный, активный
        self.sprites[0] = load_sprite(x, y, name0)
        self.sprites[1] = load_sprite(-100, -100, name1)
        all_sprites.add(self.sprites[0])
        all_sprites.draw(screen)
        pygame.display.flip()  # ...показать на форме

    def set_active(self, active):
        if self.active == active:
            return
        i0, i1 = (0, 1) if active else (1, 0)
        # меняем состояние
        self.sprites[i1].rect.x = self.x
        self.sprites[i1].rect.y = self.y
        all_sprites.remove(self.sprites[i0])
        self.sprites[i0].rect.x, self.sprites[i0].rect.y = -100, -100  # убираем совсем
        all_sprites.add(self.sprites[i1])
        all_sprites.draw(screen)
        pygame.display.flip()
        self.active = active

    def sprite(self):
        i = 1 if self.active else 0
        return self.sprites[i]


class Open_Dialog(QMainWindow):
    def __init__(self):
        super().__init__()
        self.filename = QFileDialog.getOpenFileName(
            self, 'Выбрать csv или xml файл', os.getcwd() + '/data', 'гео-файл (*.csv *xml *gpx);;Все файлы (*)')[0]


def select_File():
    app = QApplication(sys.argv)
    Open_Dialog1 = Open_Dialog()
    return Open_Dialog1.filename


def distance(lat_1, lon_1, lat_2, lon_2):
    r = 6371
    lat = (lat_2 - lat_1) * pi / 180
    lon = (lon_2 - lon_1) * pi / 180
    a = sin(lat / 2) * sin(lat / 2) + cos(lat_1 * pi / 180) * cos(lat_2 * pi / 180) * sin(lon / 2) * sin(lon / 2)
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    d = r * c
    return d


class Route:
    def __init__(self, fname):
        self.fname = fname
        self.dates = []
        self.times = []
        self.lon = []
        self.lat = []
        self.spd = []
        self.dist = []
        self.pos = []  # (x,y)
        self.start = 0  # начальный индекс
        self.finish = 0  # конечный индекс
        self.sprite_start = load_sprite(-10, -10, 'start.png', alpha=True)
        self.sprite_finish = load_sprite(-10, -10, 'finish.png', alpha=True)
        all_sprites.add(self.sprite_start)
        all_sprites.add(self.sprite_finish)
        self.points = dict()
        self.isRoute = self.load_route()

    def free(self):
        all_sprites.remove(self.sprite_start)
        all_sprites.remove(self.sprite_finish)

    def xml_to_csv(self):
        with open(self.fname) as xml_file:
            csv_txt = 'DAT;LAT;LON;SPD;Metr\n'
            tree = ET.parse(self.fname)
            root = tree.getroot()
            t1 = 0
            lat1 = float(root[1][4][0].attrib['lat'])
            lon1 = float(root[1][4][0].attrib['lon'])
            s = 0
            for child in root[1][4]:
                dt = child[1].text.replace('T', ' ')
                csv_txt += str(dt[:19]) + ';' + child.attrib['lat'] + ';' + child.attrib['lon'] + ';'

                dt = dt[11:19].split(':')
                t2 = int(dt[0]) * 3600 + int(dt[1]) * 60 + int(dt[2])
                if t1 != 0:
                    dt = t2 - t1
                else:
                    dt = 0
                t1 = t2

                lat2 = float(child.attrib['lat'])
                lon2 = float(child.attrib['lon'])
                if lat1 != root[1][4][0].attrib['lat'] and lon1 != root[1][4][0].attrib['lon']:
                    s += distance(lat1, lon1, lat2, lon2)
                    if dt != 0:
                        csv_txt += str(round(distance(lat1, lon1, lat2, lon2) * 1000 / dt * 3.6, 1)) + ';'
                    else:
                        csv_txt += str(0) + ';'
                    csv_txt += str(int(round(s, 3) * 1000)) + '\n'
                else:
                    csv_txt += str(0) + '\n'
                lat1 = float(lat2)
                lon1 = float(lon2)
            new_file = open(self.fname[:len(self.fname) - 4] + '.csv', 'w')
            new_file.write(csv_txt)
            new_file.close()
        self.fname = self.fname[:len(self.fname) - 4] + '.csv'

    def load_route(self):
        if self.fname[len(self.fname) - 4:] == '.gpx' or self.fname[len(self.fname) - 4:] == '.xml':
            self.xml_to_csv()

        with open(self.fname) as csvfile:
            reader = csv.reader(csvfile, delimiter=';', quotechar=None)
            title = next(reader)  # DAT;LAT;LON;SPD;Metr
            l = len(title)
            k = 1
            for row in reader:
                if len(row) < l:
                    continue
                k += 1
                try:
                    dt = row[0].split()
                    self.dates.append(dt[0])
                    self.times.append(dt[1])
                    self.lon.append(float(row[2]))
                    self.lat.append(float(row[1]))
                    self.spd.append(row[3])
                    self.dist.append(int(row[4]))
                    if (k - 1) % 5 == 0:
                        self.points[(float(row[1][:7]) * 10000, float(row[2][:7]) * 10000)] = [dt[0], dt[1], row[3],
                                                                                               int(row[4])]
                    self.pos.append((None, None))  # пока не знаем
                except Exception:
                    print('Ошибка в файле в строке', k)
            lon_min = min(self.lon)
            lon_max = max(self.lon)
            lat_min = min(self.lat)
            lat_max = max(self.lat)
            lon_centr = (lon_min + lon_max) / 2
            lat_centr = (lat_min + lat_max) / 2
            d_lon = lon_max - lon_min
            d_lat = lat_max - lat_min
            mp.lon = lon_centr
            mp.lat = lat_centr
            bad_size = True
            while bad_size:
                dlon, dlat = mp.map_size()
                if (dlon * 1.8 > d_lon) and (dlat * 2 > d_lat):
                    bad_size = False
                    while (dlon * 0.9 > d_lon) and (dlat > d_lat):
                        if mp.zoom < 19:
                            mp.zoom += 1
                            dlon, dlat = mp.map_size()
                        else:
                            break
                else:
                    if mp.zoom > 6:
                        mp.zoom -= 1
                    else:
                        return False  # что-то здесь не то
        return True

    def build_route(DT1=None, DT2=None):
        load_4picture(mp)


# ---- Окно для ввода разного текста ----
class Open_Dialog1(QWidget):
    def __init__(self, title, question):
        super().__init__()
        self.setGeometry(800, 400, 1, 1)
        self.result = None
        name, ok_pressed = QInputDialog.getText(self, title, question)
        if ok_pressed:
            self.result = name


def input_text(title, question):
    global input_str
    app = QApplication(sys.argv)
    ex = Open_Dialog1(title, question)
    input_str = ex.result
    ex.show()


# Ввод координат
def input_coord():
    global input_str
    input_text("Координаты", "широта, долгота (ч-з запятую)")
    if input_str:
        coord = input_str.split(',')
        try:
            lat = float(coord[0].strip())
            lon = float(coord[1].strip())
            return lon, lat
        except Exception:
            return None
    else:
        return None


# Ввод адреса
def input_adres():
    global input_str
    input_text("Введите адрес", "Нас.пункт, улица, дом")
    if input_str:
        return adres_coord(input_str)
    return None


# Печать всех строк на правом боку формы
def print_txt(mp):
    write_text("Центр карты:".format(mp.lat), 16, (255, 255, 255), 1093, 75)
    write_text("Ш:{:10.6f}".format(mp.lat), 15, (255, 255, 255), 1093, 97)
    write_text("Д:{:10.6f}".format(mp.lon), 15, (255, 255, 255), 1096, 115)
    write_text("Увеличить", 20, (255, 255, 255), 1093, 562)
    write_text("шаг", 20, (255, 255, 255), 1121, 581)
    write_text(f"Z:{mp.zoom}", 22, (255, 255, 255), 1118, 786)


# -------------------------- MAIN -------------------
if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((1200, 900))
    pygame.display.set_caption('Карта путешествий')
    clock = pygame.time.Clock()
    mp = Map()
    mp.lat = 46.30774
    mp.lon = 44.26976
    route = None  # маршрута нет
    all_sprites = pygame.sprite.Group()
    load_4picture(mp)
    cloud = None

    # Рим   mp.lat = 41.90   mp.lon = 12.51
    # СПб   mp.lat = 59.92   mp.lon = 30.35
    # Москва  mp.lat = 55.7558  mp.lon = 37.6176
    # Элиста  mp.lat = 46.30774  mp.lon = 44.26976
    # Ставрополь lat = 45.043311 lon = 41.969110

    # изображения кнопок - спрайты
    button_check = Button(1126, 525, "Check_0.png", "Check_1.png")
    button_coord = Button(1090, 15, "btn_coord0.png", "btn_coord1.png")
    button_adres = Button(1090, 150, "btn_adres0.png", "btn_adres1.png")
    button_load = Button(1090, 220, "btn_load0.png", "btn_load1.png")
    button_plus = Button(1110, 720, "btn_plus0.png", "btn_plus1.png")
    button_minus = Button(1110, 815, "btn_minus0.png", "btn_minus1.png")
    button_up = Button(1118, 380, "btnUp0.png", "btnUp1.png")
    button_down = Button(1118, 470, "btnDown0.png", "btnDown1.png")
    button_left = Button(1093, 425, "btnLeft0.png", "btnLeft1.png")
    button_right = Button(1143, 425, "btnRight0.png", "btnRight1.png")
    print_txt(mp)
    BigStep = False

    running = True
    while running:
        event = pygame.event.wait()
        if event.type == pygame.QUIT:
            running = False
            break
        elif event.type == pygame.KEYDOWN:
            if cloud:
                all_sprites.remove(cloud)
            mp.update(event.key)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if cloud:
                all_sprites.remove(cloud)
            if button_coord.sprite().rect.collidepoint(event.pos):
                button_coord.set_active(True)
                coord = input_coord()
                if coord:
                    if (-75 < coord[0] < 80) and (-180 <= coord[1] <= 180):
                        mp.lon, mp.lat = coord
                        load_4picture(mp)
                button_coord.set_active(False)
            elif button_adres.sprite().rect.collidepoint(event.pos):
                button_adres.set_active(True)
                coord = input_adres()
                if coord:
                    if (-75 < coord[0] < 80) and (-180 <= coord[1] <= 180):
                        mp.lon, mp.lat = coord
                        load_4picture(mp)
                button_adres.set_active(False)
            elif button_load.sprite().rect.collidepoint(event.pos):
                if not button_load.active:
                    button_load.set_active(True)
                    csv_file = select_File()
                    if csv_file:
                        if route:
                            route.free()
                        route = Route(csv_file)
                        if route:
                            if route.isRoute:
                                load_4picture(mp)
                    button_load.set_active(False)
            elif button_plus.sprite().rect.collidepoint(event.pos):
                button_plus.set_active(True)
                mp.update(pygame.K_PAGEUP)
                button_plus.set_active(False)
            elif button_minus.sprite().rect.collidepoint(event.pos):
                button_minus.set_active(True)
                mp.update(pygame.K_PAGEDOWN)
                button_minus.set_active(False)
            elif button_left.sprite().rect.collidepoint(event.pos):
                button_left.set_active(True)
                mp.update(pygame.K_LEFT)
                button_left.set_active(False)
            elif button_right.sprite().rect.collidepoint(event.pos):
                button_right.set_active(True)
                mp.update(pygame.K_RIGHT)
                button_right.set_active(False)
            elif button_up.sprite().rect.collidepoint(event.pos):
                button_up.set_active(True)
                mp.update(pygame.K_UP)
                button_up.set_active(False)
            elif button_down.sprite().rect.collidepoint(event.pos):
                button_down.set_active(True)
                mp.update(pygame.K_DOWN)
                button_down.set_active(False)
            elif button_check.sprite().rect.collidepoint(event.pos):
                BigStep = not button_check.active
                button_check.set_active(BigStep)
            else:
                if event.button == 1:  # LEFT_MOUSE_BUTTON
                    # print(screen.get_at((event.pos[0], event.pos[1])))
                    if (0 <= event.pos[0] < 1080) and (0 <= event.pos[1] < 900):
                        mp.add_reverse_toponym_search(event.pos)
                        lon_point, lat_point = mp.screen_to_geo((event.pos[0], event.pos[1]))
                        if ((screen.get_at((event.pos[0], event.pos[1])) == (255, 0, 0) or
                                screen.get_at((event.pos[0], event.pos[1])) == (255, 255, 0))) and \
                                ((int(lat_point * 10000), int(lon_point * 10000)) in route.points):
                            # print(mp.screen_to_geo((event.pos[0], event.pos[1])))
                            # pprint.pprint(route.points)
                            # дата, время, скорость, разгон
                            date_point = route.points[(int(lat_point * 10000), int(lon_point * 10000))][0]
                            time_point = route.points[(int(lat_point * 10000), int(lon_point * 10000))][1]
                            spd_point = route.points[(int(lat_point * 10000), int(lon_point * 10000))][2]
                            metr_point = route.points[(int(lat_point * 10000), int(lon_point * 10000))][3]

                            img = Image.open('Images/info_cloud.png')
                            font_img = ImageFont.truetype('fonts/arial.ttf', size=9)
                            draw_img = ImageDraw.Draw(img)
                            draw_img.text((64, 21), time_point[:5], font=font_img, fill=(0, 0, 0))
                            draw_img.text((53, 57), date_point[2:], font=font_img, fill=(0, 0, 0))
                            draw_img.text((167, 21), spd_point, font=font_img, fill=(0, 0, 0))
                            draw_img.text((162, 58), str(metr_point), font=font_img, fill=(0, 0, 0))
                            img.save('Images/info_cloud_tmp.png')

                            cloud = load_sprite(event.pos[0] - 158, event.pos[1] - 105, 'info_cloud_tmp.png', True)
                            all_sprites.add(cloud)
                            if os.path.exists(os.getcwd() + '\\Images\\info_cloud_tmp.png'):
                                os.remove(os.getcwd() + '\\Images\\info_cloud_tmp.png')
                            print(route.points[(int(lat_point * 10000), int(lon_point * 10000))])
                        if mp.search_result:
                            load_4picture(mp)
                elif event.button == 3:  # RIGHT_MOUSE_BUTTON
                    if (0 <= event.pos[0] < 1080) and (0 <= event.pos[1] < 900):
                        point = mp.screen_to_geo(event.pos)
                        if point:
                            mp.lon, mp.lat = point
                            load_4picture(mp)

        clock.tick(50)
    pygame.quit()
