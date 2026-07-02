"""5-month Spanish curriculum.

Structure: 20 themed weeks. Each week has 5 teaching days + 1 review day
(6 lessons/week => 120 lessons ~= 5 months at 6 lessons/week).

Each week supplies a bank of real vocabulary (Spanish + English + an example
sentence) and a set of key phrases. Daily lessons are generated deterministically
from that bank so every lesson mixes reading, listening/speaking, writing and a
quiz. Because generation is deterministic, a given lesson_id always contains the
same content for every user.
"""

# Each vocab entry: (spanish, english, example_es, example_en)
# Each phrase entry: (spanish, english)
WEEKS = [
    {
        "theme": "Saludos y cortesía", "en": "Greetings & politeness", "level": "Toddler start",
        "v": [
            ("hola", "hello", "¡Hola! ¿Cómo estás?", "Hi! How are you?"),
            ("adiós", "goodbye", "Adiós, hasta mañana.", "Goodbye, see you tomorrow."),
            ("buenos días", "good morning", "Buenos días, maestra.", "Good morning, teacher."),
            ("buenas noches", "good night", "Buenas noches, mamá.", "Good night, mom."),
            ("por favor", "please", "Agua, por favor.", "Water, please."),
            ("gracias", "thank you", "Muchas gracias.", "Thank you very much."),
            ("de nada", "you're welcome", "De nada, amigo.", "You're welcome, friend."),
            ("sí", "yes", "Sí, me gusta.", "Yes, I like it."),
            ("no", "no", "No, gracias.", "No, thank you."),
            ("perdón", "sorry / excuse me", "Perdón, no entiendo.", "Sorry, I don't understand."),
            ("amigo", "friend", "Él es mi amigo.", "He is my friend."),
            ("maestra", "teacher (f)", "La maestra es amable.", "The teacher is kind."),
        ],
        "p": [
            ("¿Cómo estás?", "How are you?"),
            ("Estoy bien.", "I am well."),
            ("Me llamo...", "My name is..."),
            ("Mucho gusto.", "Nice to meet you."),
        ],
    },
    {
        "theme": "Los colores", "en": "Colors", "level": "Beginner",
        "v": [
            ("rojo", "red", "La manzana es roja.", "The apple is red."),
            ("azul", "blue", "El cielo es azul.", "The sky is blue."),
            ("amarillo", "yellow", "El sol es amarillo.", "The sun is yellow."),
            ("verde", "green", "La hoja es verde.", "The leaf is green."),
            ("naranja", "orange", "La naranja es naranja.", "The orange is orange."),
            ("morado", "purple", "La uva es morada.", "The grape is purple."),
            ("rosa", "pink", "La flor es rosa.", "The flower is pink."),
            ("negro", "black", "El gato es negro.", "The cat is black."),
            ("blanco", "white", "La nube es blanca.", "The cloud is white."),
            ("marrón", "brown", "El oso es marrón.", "The bear is brown."),
            ("gris", "gray", "El elefante es gris.", "The elephant is gray."),
            ("color", "color", "¿Cuál es tu color favorito?", "What is your favorite color?"),
        ],
        "p": [
            ("Me gusta el rojo.", "I like red."),
            ("¿De qué color es?", "What color is it?"),
            ("Es de color azul.", "It is blue."),
        ],
    },
    {
        "theme": "Los números 0–20", "en": "Numbers 0–20", "level": "Beginner",
        "v": [
            ("cero", "zero", "Tengo cero dulces.", "I have zero candies."),
            ("uno", "one", "Hay un perro.", "There is one dog."),
            ("dos", "two", "Tengo dos manos.", "I have two hands."),
            ("tres", "three", "Veo tres gatos.", "I see three cats."),
            ("cuatro", "four", "La mesa tiene cuatro patas.", "The table has four legs."),
            ("cinco", "five", "Una mano tiene cinco dedos.", "A hand has five fingers."),
            ("seis", "six", "Son las seis.", "It is six o'clock."),
            ("siete", "seven", "Hay siete días.", "There are seven days."),
            ("ocho", "eight", "Tengo ocho años.", "I am eight years old."),
            ("nueve", "nine", "Faltan nueve.", "Nine are missing."),
            ("diez", "ten", "Cuenta hasta diez.", "Count to ten."),
            ("veinte", "twenty", "Hay veinte niños.", "There are twenty children."),
        ],
        "p": [
            ("¿Cuántos años tienes?", "How old are you?"),
            ("Tengo cinco años.", "I am five years old."),
            ("Cuenta conmigo.", "Count with me."),
        ],
    },
    {
        "theme": "La familia", "en": "Family", "level": "Beginner",
        "v": [
            ("mamá", "mom", "Mi mamá cocina.", "My mom cooks."),
            ("papá", "dad", "Mi papá trabaja.", "My dad works."),
            ("hermano", "brother", "Mi hermano juega.", "My brother plays."),
            ("hermana", "sister", "Mi hermana canta.", "My sister sings."),
            ("abuelo", "grandfather", "Mi abuelo lee.", "My grandfather reads."),
            ("abuela", "grandmother", "Mi abuela sonríe.", "My grandmother smiles."),
            ("bebé", "baby", "El bebé duerme.", "The baby sleeps."),
            ("tío", "uncle", "Mi tío es alto.", "My uncle is tall."),
            ("tía", "aunt", "Mi tía es doctora.", "My aunt is a doctor."),
            ("primo", "cousin (m)", "Mi primo corre.", "My cousin runs."),
            ("familia", "family", "Amo a mi familia.", "I love my family."),
            ("hijo", "son", "Su hijo es amable.", "Their son is kind."),
        ],
        "p": [
            ("Esta es mi familia.", "This is my family."),
            ("Tengo un hermano.", "I have one brother."),
            ("Te quiero mucho.", "I love you very much."),
        ],
    },
    {
        "theme": "El cuerpo", "en": "The body", "level": "Beginner",
        "v": [
            ("cabeza", "head", "Muevo la cabeza.", "I move my head."),
            ("ojo", "eye", "Tengo dos ojos.", "I have two eyes."),
            ("nariz", "nose", "Huelo con la nariz.", "I smell with my nose."),
            ("boca", "mouth", "Como con la boca.", "I eat with my mouth."),
            ("oreja", "ear", "Escucho con la oreja.", "I listen with my ear."),
            ("mano", "hand", "Aplaudo con las manos.", "I clap with my hands."),
            ("pie", "foot", "Camino con los pies.", "I walk with my feet."),
            ("brazo", "arm", "Levanto el brazo.", "I raise my arm."),
            ("pierna", "leg", "Corro con las piernas.", "I run with my legs."),
            ("pelo", "hair", "Mi pelo es negro.", "My hair is black."),
            ("diente", "tooth", "Cepillo mis dientes.", "I brush my teeth."),
            ("dedo", "finger", "Señalo con el dedo.", "I point with my finger."),
        ],
        "p": [
            ("Me duele la cabeza.", "My head hurts."),
            ("Toca tu nariz.", "Touch your nose."),
            ("Levanta la mano.", "Raise your hand."),
        ],
    },
    {
        "theme": "Los animales", "en": "Animals", "level": "Beginner",
        "v": [
            ("perro", "dog", "El perro ladra.", "The dog barks."),
            ("gato", "cat", "El gato duerme.", "The cat sleeps."),
            ("pájaro", "bird", "El pájaro vuela.", "The bird flies."),
            ("pez", "fish", "El pez nada.", "The fish swims."),
            ("caballo", "horse", "El caballo corre.", "The horse runs."),
            ("vaca", "cow", "La vaca come pasto.", "The cow eats grass."),
            ("cerdo", "pig", "El cerdo es rosa.", "The pig is pink."),
            ("pollo", "chicken", "El pollo pía.", "The chicken chirps."),
            ("ratón", "mouse", "El ratón es pequeño.", "The mouse is small."),
            ("conejo", "rabbit", "El conejo salta.", "The rabbit jumps."),
            ("león", "lion", "El león ruge.", "The lion roars."),
            ("oso", "bear", "El oso es grande.", "The bear is big."),
        ],
        "p": [
            ("¿Qué animal es?", "What animal is it?"),
            ("Me gustan los perros.", "I like dogs."),
            ("El gato dice miau.", "The cat says meow."),
        ],
    },
    {
        "theme": "La comida", "en": "Food", "level": "Beginner",
        "v": [
            ("agua", "water", "Bebo agua.", "I drink water."),
            ("leche", "milk", "La leche es blanca.", "Milk is white."),
            ("pan", "bread", "Como pan.", "I eat bread."),
            ("manzana", "apple", "La manzana es dulce.", "The apple is sweet."),
            ("plátano", "banana", "El plátano es amarillo.", "The banana is yellow."),
            ("huevo", "egg", "Como un huevo.", "I eat an egg."),
            ("queso", "cheese", "Me gusta el queso.", "I like cheese."),
            ("arroz", "rice", "El arroz es blanco.", "Rice is white."),
            ("pollo", "chicken", "Comemos pollo.", "We eat chicken."),
            ("sopa", "soup", "La sopa está caliente.", "The soup is hot."),
            ("fruta", "fruit", "Compro fruta.", "I buy fruit."),
            ("comida", "food", "La comida está rica.", "The food is tasty."),
        ],
        "p": [
            ("Tengo hambre.", "I am hungry."),
            ("Tengo sed.", "I am thirsty."),
            ("Está delicioso.", "It is delicious."),
        ],
    },
    {
        "theme": "La ropa", "en": "Clothes", "level": "Beginner",
        "v": [
            ("camisa", "shirt", "La camisa es azul.", "The shirt is blue."),
            ("pantalón", "pants", "El pantalón es negro.", "The pants are black."),
            ("zapato", "shoe", "Mis zapatos son rojos.", "My shoes are red."),
            ("vestido", "dress", "El vestido es bonito.", "The dress is pretty."),
            ("sombrero", "hat", "Llevo un sombrero.", "I wear a hat."),
            ("abrigo", "coat", "Hace frío, usa abrigo.", "It is cold, wear a coat."),
            ("calcetín", "sock", "Un calcetín es blanco.", "One sock is white."),
            ("falda", "skirt", "La falda es verde.", "The skirt is green."),
            ("guante", "glove", "Uso guantes en invierno.", "I wear gloves in winter."),
            ("bufanda", "scarf", "La bufanda es larga.", "The scarf is long."),
            ("ropa", "clothes", "Guardo mi ropa.", "I put away my clothes."),
            ("botas", "boots", "Las botas son cafés.", "The boots are brown."),
        ],
        "p": [
            ("Me pongo los zapatos.", "I put on my shoes."),
            ("¿Qué llevas puesto?", "What are you wearing?"),
            ("Hace frío hoy.", "It is cold today."),
        ],
    },
    {
        "theme": "La casa", "en": "The house", "level": "Elementary",
        "v": [
            ("casa", "house", "Mi casa es grande.", "My house is big."),
            ("puerta", "door", "Abre la puerta.", "Open the door."),
            ("ventana", "window", "La ventana está abierta.", "The window is open."),
            ("cocina", "kitchen", "Cocino en la cocina.", "I cook in the kitchen."),
            ("baño", "bathroom", "El baño está limpio.", "The bathroom is clean."),
            ("cama", "bed", "Duermo en la cama.", "I sleep in the bed."),
            ("mesa", "table", "La comida está en la mesa.", "The food is on the table."),
            ("silla", "chair", "Me siento en la silla.", "I sit on the chair."),
            ("cuarto", "room", "Mi cuarto es azul.", "My room is blue."),
            ("luz", "light", "Enciende la luz.", "Turn on the light."),
            ("jardín", "garden", "Juego en el jardín.", "I play in the garden."),
            ("llave", "key", "¿Dónde está la llave?", "Where is the key?"),
        ],
        "p": [
            ("Estoy en casa.", "I am at home."),
            ("Ven a mi casa.", "Come to my house."),
            ("¿Dónde está el baño?", "Where is the bathroom?"),
        ],
    },
    {
        "theme": "Números 20–100 y la hora", "en": "Numbers 20–100 & time", "level": "Elementary",
        "v": [
            ("treinta", "thirty", "Tengo treinta libros.", "I have thirty books."),
            ("cuarenta", "forty", "Hay cuarenta sillas.", "There are forty chairs."),
            ("cincuenta", "fifty", "Cuesta cincuenta pesos.", "It costs fifty pesos."),
            ("sesenta", "sixty", "Un minuto tiene sesenta segundos.", "A minute has sixty seconds."),
            ("setenta", "seventy", "Mi abuela tiene setenta años.", "My grandma is seventy."),
            ("ochenta", "eighty", "Faltan ochenta días.", "Eighty days are left."),
            ("noventa", "ninety", "Hay noventa puntos.", "There are ninety points."),
            ("cien", "one hundred", "Cuenta hasta cien.", "Count to one hundred."),
            ("hora", "hour / time", "¿Qué hora es?", "What time is it?"),
            ("minuto", "minute", "Espera un minuto.", "Wait a minute."),
            ("media", "half (past)", "Son las dos y media.", "It is half past two."),
            ("reloj", "clock", "El reloj es nuevo.", "The clock is new."),
        ],
        "p": [
            ("¿Qué hora es?", "What time is it?"),
            ("Son las tres.", "It is three o'clock."),
            ("Es la una y media.", "It is half past one."),
        ],
    },
    {
        "theme": "Días y meses", "en": "Days & months", "level": "Elementary",
        "v": [
            ("lunes", "Monday", "El lunes voy a la escuela.", "On Monday I go to school."),
            ("martes", "Tuesday", "El martes tengo clase.", "On Tuesday I have class."),
            ("miércoles", "Wednesday", "El miércoles llueve.", "On Wednesday it rains."),
            ("jueves", "Thursday", "El jueves juego fútbol.", "On Thursday I play soccer."),
            ("viernes", "Friday", "El viernes descanso.", "On Friday I rest."),
            ("sábado", "Saturday", "El sábado voy al parque.", "On Saturday I go to the park."),
            ("domingo", "Sunday", "El domingo veo a mi familia.", "On Sunday I see my family."),
            ("enero", "January", "En enero hace frío.", "In January it is cold."),
            ("julio", "July", "En julio hace calor.", "In July it is hot."),
            ("hoy", "today", "Hoy es lunes.", "Today is Monday."),
            ("mañana", "tomorrow", "Mañana es martes.", "Tomorrow is Tuesday."),
            ("semana", "week", "La semana tiene siete días.", "The week has seven days."),
        ],
        "p": [
            ("¿Qué día es hoy?", "What day is it today?"),
            ("Hoy es viernes.", "Today is Friday."),
            ("Nos vemos mañana.", "See you tomorrow."),
        ],
    },
    {
        "theme": "El clima y las estaciones", "en": "Weather & seasons", "level": "Elementary",
        "v": [
            ("sol", "sun", "Hace sol hoy.", "It is sunny today."),
            ("lluvia", "rain", "La lluvia es fría.", "The rain is cold."),
            ("nieve", "snow", "La nieve es blanca.", "The snow is white."),
            ("viento", "wind", "El viento es fuerte.", "The wind is strong."),
            ("nube", "cloud", "Hay muchas nubes.", "There are many clouds."),
            ("calor", "heat", "Tengo calor.", "I am hot."),
            ("frío", "cold", "Tengo frío.", "I am cold."),
            ("primavera", "spring", "En primavera hay flores.", "In spring there are flowers."),
            ("verano", "summer", "En verano vamos a la playa.", "In summer we go to the beach."),
            ("otoño", "autumn", "En otoño caen las hojas.", "In autumn the leaves fall."),
            ("invierno", "winter", "En invierno nieva.", "In winter it snows."),
            ("tiempo", "weather", "¿Qué tiempo hace?", "What is the weather like?"),
        ],
        "p": [
            ("¿Qué tiempo hace?", "What is the weather like?"),
            ("Hace buen tiempo.", "The weather is nice."),
            ("Está lloviendo.", "It is raining."),
        ],
    },
    {
        "theme": "Verbos comunes (presente)", "en": "Common verbs (present)", "level": "Intermediate",
        "v": [
            ("ser", "to be (traits)", "Yo soy alto.", "I am tall."),
            ("estar", "to be (state)", "Estoy cansado.", "I am tired."),
            ("tener", "to have", "Tengo un libro.", "I have a book."),
            ("hacer", "to do / make", "Hago mi tarea.", "I do my homework."),
            ("ir", "to go", "Voy a la escuela.", "I go to school."),
            ("comer", "to eat", "Como fruta.", "I eat fruit."),
            ("beber", "to drink", "Bebo agua.", "I drink water."),
            ("hablar", "to speak", "Hablo español.", "I speak Spanish."),
            ("querer", "to want", "Quiero jugar.", "I want to play."),
            ("jugar", "to play", "Juego con mi amigo.", "I play with my friend."),
            ("ver", "to see", "Veo la televisión.", "I watch television."),
            ("vivir", "to live", "Vivo en la ciudad.", "I live in the city."),
        ],
        "p": [
            ("Quiero aprender español.", "I want to learn Spanish."),
            ("Voy a comer.", "I am going to eat."),
            ("Yo hablo un poco.", "I speak a little."),
        ],
    },
    {
        "theme": "En la escuela", "en": "At school", "level": "Intermediate",
        "v": [
            ("escuela", "school", "Voy a la escuela.", "I go to school."),
            ("libro", "book", "Leo un libro.", "I read a book."),
            ("lápiz", "pencil", "Escribo con un lápiz.", "I write with a pencil."),
            ("papel", "paper", "Dibujo en el papel.", "I draw on the paper."),
            ("maestro", "teacher (m)", "El maestro enseña.", "The teacher teaches."),
            ("clase", "class", "La clase es divertida.", "The class is fun."),
            ("tarea", "homework", "Hago la tarea.", "I do the homework."),
            ("compañero", "classmate", "Mi compañero estudia.", "My classmate studies."),
            ("leer", "to read", "Me gusta leer.", "I like to read."),
            ("escribir", "to write", "Voy a escribir.", "I am going to write."),
            ("aprender", "to learn", "Quiero aprender.", "I want to learn."),
            ("pregunta", "question", "Tengo una pregunta.", "I have a question."),
        ],
        "p": [
            ("No entiendo.", "I don't understand."),
            ("¿Puedes repetir?", "Can you repeat?"),
            ("¿Cómo se dice...?", "How do you say...?"),
        ],
    },
    {
        "theme": "La ciudad y direcciones", "en": "The city & directions", "level": "Intermediate",
        "v": [
            ("ciudad", "city", "La ciudad es grande.", "The city is big."),
            ("calle", "street", "Cruzo la calle.", "I cross the street."),
            ("tienda", "store", "Voy a la tienda.", "I go to the store."),
            ("parque", "park", "Jugamos en el parque.", "We play in the park."),
            ("coche", "car", "El coche es rojo.", "The car is red."),
            ("autobús", "bus", "Tomo el autobús.", "I take the bus."),
            ("izquierda", "left", "Gira a la izquierda.", "Turn left."),
            ("derecha", "right", "Gira a la derecha.", "Turn right."),
            ("recto", "straight", "Sigue recto.", "Go straight."),
            ("cerca", "near", "La tienda está cerca.", "The store is near."),
            ("lejos", "far", "La escuela está lejos.", "The school is far."),
            ("hospital", "hospital", "El hospital está allí.", "The hospital is over there."),
        ],
        "p": [
            ("¿Dónde está...?", "Where is...?"),
            ("Está a la derecha.", "It is on the right."),
            ("Sigue recto, por favor.", "Go straight, please."),
        ],
    },
    {
        "theme": "Las emociones", "en": "Emotions", "level": "Intermediate",
        "v": [
            ("feliz", "happy", "Estoy feliz.", "I am happy."),
            ("triste", "sad", "Ella está triste.", "She is sad."),
            ("enojado", "angry", "Él está enojado.", "He is angry."),
            ("cansado", "tired", "Estoy cansado.", "I am tired."),
            ("asustado", "scared", "El niño está asustado.", "The child is scared."),
            ("emocionado", "excited", "Estoy emocionado.", "I am excited."),
            ("aburrido", "bored", "Estoy aburrido.", "I am bored."),
            ("nervioso", "nervous", "Estoy nervioso.", "I am nervous."),
            ("tranquilo", "calm", "Estoy tranquilo.", "I am calm."),
            ("contento", "glad", "Estoy contento hoy.", "I am glad today."),
            ("enfermo", "sick", "Estoy enfermo.", "I am sick."),
            ("sorprendido", "surprised", "Estoy sorprendido.", "I am surprised."),
        ],
        "p": [
            ("¿Cómo te sientes?", "How do you feel?"),
            ("Me siento feliz.", "I feel happy."),
            ("Estoy un poco cansado.", "I am a little tired."),
        ],
    },
    {
        "theme": "De compras", "en": "Shopping", "level": "Upper-intermediate",
        "v": [
            ("dinero", "money", "No tengo dinero.", "I don't have money."),
            ("precio", "price", "¿Cuál es el precio?", "What is the price?"),
            ("comprar", "to buy", "Quiero comprar pan.", "I want to buy bread."),
            ("vender", "to sell", "Ellos venden fruta.", "They sell fruit."),
            ("caro", "expensive", "Es muy caro.", "It is very expensive."),
            ("barato", "cheap", "Es barato.", "It is cheap."),
            ("mercado", "market", "Voy al mercado.", "I go to the market."),
            ("pagar", "to pay", "Voy a pagar ahora.", "I am going to pay now."),
            ("bolsa", "bag", "Pon todo en la bolsa.", "Put everything in the bag."),
            ("cambio", "change (money)", "Aquí está tu cambio.", "Here is your change."),
            ("tarjeta", "card", "Pago con tarjeta.", "I pay with a card."),
            ("cuánto", "how much", "¿Cuánto cuesta?", "How much does it cost?"),
        ],
        "p": [
            ("¿Cuánto cuesta?", "How much does it cost?"),
            ("Quiero comprar esto.", "I want to buy this."),
            ("¿Aceptan tarjeta?", "Do you take cards?"),
        ],
    },
    {
        "theme": "Viajes y transporte", "en": "Travel & transport", "level": "Upper-intermediate",
        "v": [
            ("viaje", "trip", "El viaje es largo.", "The trip is long."),
            ("avión", "airplane", "El avión es rápido.", "The airplane is fast."),
            ("tren", "train", "Tomo el tren.", "I take the train."),
            ("boleto", "ticket", "Compro un boleto.", "I buy a ticket."),
            ("maleta", "suitcase", "Mi maleta es pesada.", "My suitcase is heavy."),
            ("aeropuerto", "airport", "Voy al aeropuerto.", "I go to the airport."),
            ("hotel", "hotel", "El hotel es cómodo.", "The hotel is comfortable."),
            ("playa", "beach", "Vamos a la playa.", "We go to the beach."),
            ("mapa", "map", "Miro el mapa.", "I look at the map."),
            ("salir", "to leave", "El tren sale a las ocho.", "The train leaves at eight."),
            ("llegar", "to arrive", "Llego mañana.", "I arrive tomorrow."),
            ("pasaporte", "passport", "¿Dónde está mi pasaporte?", "Where is my passport?"),
        ],
        "p": [
            ("Quiero un boleto, por favor.", "I want a ticket, please."),
            ("¿A qué hora sale?", "What time does it leave?"),
            ("Buen viaje.", "Have a good trip."),
        ],
    },
    {
        "theme": "El trabajo y profesiones", "en": "Work & professions", "level": "Advanced",
        "v": [
            ("trabajo", "work / job", "Me gusta mi trabajo.", "I like my job."),
            ("médico", "doctor", "El médico ayuda a la gente.", "The doctor helps people."),
            ("maestra", "teacher (f)", "La maestra es paciente.", "The teacher is patient."),
            ("policía", "police officer", "El policía es valiente.", "The police officer is brave."),
            ("cocinero", "cook", "El cocinero prepara la cena.", "The cook prepares dinner."),
            ("bombero", "firefighter", "El bombero apaga el fuego.", "The firefighter puts out the fire."),
            ("ingeniero", "engineer", "El ingeniero diseña puentes.", "The engineer designs bridges."),
            ("artista", "artist", "La artista pinta.", "The artist paints."),
            ("oficina", "office", "Trabajo en una oficina.", "I work in an office."),
            ("jefe", "boss", "Mi jefe es amable.", "My boss is kind."),
            ("ganar", "to earn", "Gano dinero.", "I earn money."),
            ("reunión", "meeting", "Tengo una reunión hoy.", "I have a meeting today."),
        ],
        "p": [
            ("¿En qué trabajas?", "What do you do for work?"),
            ("Soy estudiante.", "I am a student."),
            ("Trabajo en una escuela.", "I work at a school."),
        ],
    },
    {
        "theme": "Conversación y repaso", "en": "Conversation & review", "level": "Advanced",
        "v": [
            ("creer", "to believe / think", "Creo que sí.", "I think so."),
            ("saber", "to know (facts)", "No sé la respuesta.", "I don't know the answer."),
            ("conocer", "to know (people)", "Conozco a María.", "I know María."),
            ("poder", "to be able to", "Puedo ayudarte.", "I can help you."),
            ("deber", "should / must", "Debo estudiar.", "I must study."),
            ("necesitar", "to need", "Necesito ayuda.", "I need help."),
            ("entender", "to understand", "Ahora entiendo.", "Now I understand."),
            ("esperar", "to wait / hope", "Espero verte pronto.", "I hope to see you soon."),
            ("porque", "because", "Estudio porque quiero aprender.", "I study because I want to learn."),
            ("pero", "but", "Quiero ir, pero no puedo.", "I want to go, but I cannot."),
            ("también", "also", "Yo también hablo español.", "I also speak Spanish."),
            ("siempre", "always", "Siempre practico.", "I always practice."),
        ],
        "p": [
            ("Creo que tienes razón.", "I think you are right."),
            ("¿Qué piensas?", "What do you think?"),
            ("¡Hablo español muy bien!", "I speak Spanish very well!"),
        ],
    },
]

DAYS_PER_WEEK = 6   # 5 teaching days + 1 review
TEACHING_DAYS = 5


def _vocab(v):
    return {"es": v[0], "en": v[1], "exampleEs": v[2], "exampleEn": v[3]}


def _phrase(p):
    return {"es": p[0], "en": p[1]}


def _slice(arr, start, count):
    out = []
    n = len(arr)
    for i in range(min(count, n)):
        out.append(arr[(start + i) % n])
    return out


def _build_lesson(week_index, day_index):
    week = WEEKS[week_index]
    is_review = day_index == TEACHING_DAYS
    week_num = week_index + 1
    day_num = day_index + 1
    lid = f"w{week_num}d{day_num}"

    if is_review:
        return {
            "id": lid, "week": week_num, "day": day_num,
            "theme": week["theme"], "themeEn": week["en"], "level": week["level"],
            "title": f"Repaso — {week['theme']}", "titleEn": f"Review — {week['en']}",
            "isReview": True, "focus": ["read", "listen", "speak", "write", "quiz"],
            "vocab": [_vocab(v) for v in week["v"]],
            "phrases": [_phrase(p) for p in week["p"]],
        }

    chunk = 4
    start = day_index * chunk
    day_vocab = _slice(week["v"], start, chunk + 2)
    return {
        "id": lid, "week": week_num, "day": day_num,
        "theme": week["theme"], "themeEn": week["en"], "level": week["level"],
        "title": f"{week['theme']} — parte {day_num}",
        "titleEn": f"{week['en']} — part {day_num}",
        "isReview": False, "focus": ["read", "listen", "quiz"],
        "vocab": [_vocab(v) for v in day_vocab],
        "phrases": [_phrase(p) for p in _slice(week["p"], day_index, min(2, len(week["p"])))],
    }


def build_curriculum():
    weeks = []
    lesson_count = 0
    for w in range(len(WEEKS)):
        lessons = []
        for d in range(DAYS_PER_WEEK):
            lessons.append(_build_lesson(w, d))
            lesson_count += 1
        weeks.append({
            "week": w + 1,
            "theme": WEEKS[w]["theme"], "themeEn": WEEKS[w]["en"], "level": WEEKS[w]["level"],
            "month": (w // 4) + 1,   # 4 weeks per month => 5 months
            "lessons": lessons,
        })
    return {
        "totalWeeks": len(WEEKS), "totalMonths": 5, "daysPerWeek": DAYS_PER_WEEK,
        "totalLessons": lesson_count, "weeks": weeks,
    }


CURRICULUM = build_curriculum()
LESSON_IDS = {l["id"] for wk in CURRICULUM["weeks"] for l in wk["lessons"]}
