from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import requests
import os

app = Flask(__name__)
app.secret_key = 'some_secret_key'  # Pas dit aan voor jouw productieomgeving
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///catering.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Constantes
ORIGIN_ADDRESS = "9271CL"  # Vaste oorsprong
DEFAULT_COST_PER_KM = 0.25  # Standaardprijs per kilometer

# Database model voor buffetopties
class BuffetOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    price_per_person = db.Column(db.Float, nullable=True)
    min_total = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f"<BuffetOption {self.name}>"

def init_db():
    db.create_all()
    # Voeg de opties toe als de tabel nog leeg is
    if BuffetOption.query.count() == 0:
        options = [
            {"name": "Levensgenieter", "price_per_person": 25.0, "min_total": 500.0},
            {"name": "Smulbuffet", "price_per_person": 20.0, "min_total": 400.0},
            {"name": "de Westereen", "price_per_person": 32.5, "min_total": 650.0},
            {"name": "Barbecue", "price_per_person": 25.0, "min_total": 500.0},
            {"name": "Maaltijdbuffet", "price_per_person": 20.0, "min_total": 400.0},
            {"name": "Boerenbuffet", "price_per_person": 20.0, "min_total": 400.0},
            {"name": "Stampot", "price_per_person": 18.5, "min_total": 370.0},
            {"name": "Aangepast buffet", "price_per_person": None, "min_total": None},
        ]
        for opt in options:
            buffet = BuffetOption(
                name=opt["name"],
                price_per_person=opt["price_per_person"],
                min_total=opt["min_total"]
            )
            db.session.add(buffet)
        db.session.commit()

def geocode_address(address):
    """
    Haalt de lat/lon-coördinaten op via de Nominatim API.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "CateringCalculator/1.0 (your_email@example.com)"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=60)
        data = response.json()
        if data:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            return (lat, lon)
        else:
            return None
    except Exception as e:
        print("Geocode error:", e)
        return None

def get_route_data(origin_coords, dest_coords):
    """
    Berekent de route-afstand (in km) en haalt de route-geometrie (GeoJSON) op.
    OSRM verwacht coördinaten in lon,lat volgorde.
    """
    lon1, lat1 = origin_coords[1], origin_coords[0]
    lon2, lat2 = dest_coords[1], dest_coords[0]
    url = f"https://routing.openstreetmap.de/routed-car/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
    params = {
        "overview": "full",       # Geeft een volledige route-geometrie terug
        "geometries": "geojson"   # In GeoJSON-formaat
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data and "routes" in data and len(data["routes"]) > 0:
            distance_m = data["routes"][0]["distance"]
            distance_km = distance_m / 1000.0
            geometry = data["routes"][0]["geometry"]
            return distance_km, geometry
        else:
            return None, None
    except Exception as e:
        print("Routing error:", e)
        return None, None

@app.route("/", methods=["GET", "POST"])
def index():
    buffet_options = BuffetOption.query.all()
    if request.method == "POST":
        buffet_name = request.form.get("buffet")
        persons = request.form.get("persons")
        use_min = request.form.get("use_min")
        destination_address = request.form.get("destination")
        cost_per_km_input = request.form.get("cost_per_km")

        # Validatie van invoer
        try:
            persons = int(persons)
        except ValueError:
            flash("Voer een geldig aantal personen in.")
            return redirect(url_for("index"))

        try:
            cost_per_km = float(cost_per_km_input)
        except ValueError:
            flash("Voer een geldige prijs per kilometer in.")
            return redirect(url_for("index"))

        # Haal de geselecteerde buffetoptie op
        option = BuffetOption.query.filter_by(name=buffet_name).first()
        if not option:
            flash("Ongeldige buffet optie.")
            return redirect(url_for("index"))

        # Bepaal prijs per persoon en minimale totaalprijs
        if buffet_name != "Aangepast buffet":
            price_per_person = option.price_per_person
            min_total = option.min_total
        else:
            try:
                price_per_person = float(request.form.get("custom_price"))
                min_total = float(request.form.get("custom_min"))
            except (TypeError, ValueError):
                flash("Voer geldige getallen in voor aangepast buffet.")
                return redirect(url_for("index"))

        # Bereken de cateringkosten
        catering_cost = persons * price_per_person
        if use_min == "on":
            catering_cost = max(catering_cost, min_total)

        # Geocode de adressen
        origin_coords = geocode_address(ORIGIN_ADDRESS)
        dest_coords = geocode_address(destination_address)

        if origin_coords is None or dest_coords is None:
            flash("Adres niet gevonden.")
            return redirect(url_for("index"))

        # Haal afstand en route-geometrie op
        distance_km, route_geometry = get_route_data(origin_coords, dest_coords)
        if distance_km is None:
            flash("Fout bij het berekenen van de route.")
            return redirect(url_for("index"))

        # Bereken de bezorgkosten
        if distance_km < 5:
            route_cost = 0.0
        else:
            route_cost = distance_km * 4 * cost_per_km

        total_cost = catering_cost + route_cost

        # Bereid de resultaten voor, inclusief de route-geometrie
        result = {
            "catering_cost": f"€{catering_cost:.2f}",
            "distance_km": f"{distance_km:.2f} km",
            "route_cost": f"€{route_cost:.2f}",
            "total_cost": f"€{total_cost:.2f}",
            "route_geometry": route_geometry  # Dit is een dict in GeoJSON-formaat
        }

        return render_template("result.html", result=result)

    return render_template("index.html", buffet_options=buffet_options, default_cost_per_km=DEFAULT_COST_PER_KM)


if __name__ == "__main__":
    with app.app_context():
        if not os.path.exists("catering.db"):
            init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)

# cd C:\Users\janyp\Desktop\Files\Cateringapp
# python app.py
# http://192.168.1.90:5000
