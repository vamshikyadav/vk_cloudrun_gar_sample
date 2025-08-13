FROM maven:3.9-eclipse-temurin-17
WORKDIR /app
COPY pom.xml .
RUN mvn -q dependency:go-offline
COPY src ./src
RUN mvn -q package -DskipTests
EXPOSE 8080
ENV PORT=8080
CMD ["java", "-jar", "target/cloudrun-demo-0.0.1.jar"]