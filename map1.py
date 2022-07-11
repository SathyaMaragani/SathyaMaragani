import folium
#need to install folium in terminal for this to work
#command- pip install folium

map = folium.Map(location=[17.41, 74.4], zoom_start=6, tiles="Stamen terrain")


fg = folium.FeatureGroup(name="My Map")
fg.add_child(folium.Marker(location=[17.42091554494413, 78.43030645580453], popup="Lucky House", icon=folium.Icon(color='blue')))
map.add_child(fg)

map.save("Map1.html")
