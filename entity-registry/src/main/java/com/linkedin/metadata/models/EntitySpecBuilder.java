package com.linkedin.metadata.models;

import com.google.common.collect.ImmutableList;
import com.linkedin.data.schema.ArrayDataSchema;
import com.linkedin.data.schema.DataSchema;
import com.linkedin.data.schema.RecordDataSchema;
import com.linkedin.data.schema.TyperefDataSchema;
import com.linkedin.data.schema.UnionDataSchema;
import com.linkedin.data.schema.annotation.DataSchemaRichContextTraverser;
import com.linkedin.data.schema.annotation.PegasusSchemaAnnotationHandlerImpl;
import com.linkedin.data.schema.annotation.SchemaAnnotationHandler;
import com.linkedin.data.schema.annotation.SchemaAnnotationProcessor;
import com.linkedin.metadata.models.annotation.AspectAnnotation;
import com.linkedin.metadata.models.annotation.EntityAnnotation;
import com.linkedin.metadata.models.annotation.RelationshipAnnotation;
import com.linkedin.metadata.models.annotation.SearchableAnnotation;
import com.linkedin.metadata.models.annotation.TimeseriesFieldAnnotation;
import com.linkedin.metadata.models.annotation.TimeseriesFieldCollectionAnnotation;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import javax.annotation.Nonnull;
import lombok.extern.slf4j.Slf4j;


@Slf4j
public class EntitySpecBuilder {

  private static final String URN_FIELD_NAME = "urn";
  private static final String ASPECTS_FIELD_NAME = "aspects";
  private static final String TIMESTAMP_FIELD_NAME = "timestampMillis";

  public static SchemaAnnotationHandler _searchHandler =
      new PegasusSchemaAnnotationHandlerImpl(SearchableAnnotation.ANNOTATION_NAME);
  public static SchemaAnnotationHandler _relationshipHandler =
      new PegasusSchemaAnnotationHandlerImpl(RelationshipAnnotation.ANNOTATION_NAME);
  public static SchemaAnnotationHandler _timeseriesFiledAnnotationHandler =
      new PegasusSchemaAnnotationHandlerImpl(TimeseriesFieldAnnotation.ANNOTATION_NAME);
  public static SchemaAnnotationHandler _timeseriesFieldCollectionHandler =
      new PegasusSchemaAnnotationHandlerImpl(TimeseriesFieldCollectionAnnotation.ANNOTATION_NAME);

  private final AnnotationExtractionMode _extractionMode;
  private final Set<String> _entityNames = new HashSet<>();
  private final Set<RelationshipFieldSpec> _relationshipFieldSpecs = new HashSet<>();

  public EntitySpecBuilder() {
    this(AnnotationExtractionMode.DEFAULT);
  }

  public EntitySpecBuilder(final AnnotationExtractionMode extractionMode) {
    _extractionMode = extractionMode;
  }

  public List<EntitySpec> buildEntitySpecs(@Nonnull final DataSchema snapshotSchema) {

    final UnionDataSchema snapshotUnionSchema = (UnionDataSchema) snapshotSchema.getDereferencedDataSchema();
    final List<UnionDataSchema.Member> unionMembers = snapshotUnionSchema.getMembers();

    final List<EntitySpec> entitySpecs = new ArrayList<>();
    for (final UnionDataSchema.Member member : unionMembers) {
      final EntitySpec entitySpec = buildEntitySpec(member.getType());
      if (entitySpec != null) {
        entitySpecs.add(entitySpec);
      }
    }

    // Now validate that all relationships point to valid entities.
    for (final RelationshipFieldSpec spec : _relationshipFieldSpecs) {
      if (!_entityNames.containsAll(
          spec.getValidDestinationTypes().stream().map(String::toLowerCase).collect(Collectors.toList()))) {
        failValidation(
            String.format("Found invalid relationship with name %s at path %s. Invalid entityType(s) provided.",
                spec.getRelationshipName(), spec.getPath()));
      }
    }

    return entitySpecs;
  }

  public EntitySpec buildEntitySpec(@Nonnull final DataSchema entitySnapshotSchema) {

    // 0. Validate the Snapshot definition
    final RecordDataSchema entitySnapshotRecordSchema = validateSnapshot(entitySnapshotSchema);

    // 1. Parse information about the entity from the "entity" annotation.
    final Object entityAnnotationObj = entitySnapshotRecordSchema.getProperties().get(EntityAnnotation.ANNOTATION_NAME);

    if (entityAnnotationObj != null) {

      EntityAnnotation entityAnnotation =
          EntityAnnotation.fromSchemaProperty(entityAnnotationObj, entitySnapshotRecordSchema.getFullName());

      final ArrayDataSchema aspectArraySchema =
          (ArrayDataSchema) entitySnapshotRecordSchema.getField(ASPECTS_FIELD_NAME)
              .getType()
              .getDereferencedDataSchema();

      final UnionDataSchema aspectUnionSchema =
          (UnionDataSchema) aspectArraySchema.getItems().getDereferencedDataSchema();

      final List<UnionDataSchema.Member> unionMembers = aspectUnionSchema.getMembers();
      final List<AspectSpec> aspectSpecs = new ArrayList<>();
      for (final UnionDataSchema.Member member : unionMembers) {
        final AspectSpec spec = buildAspectSpec(member.getType());
        aspectSpecs.add(spec);
      }

      final EntitySpec entitySpec = new DefaultEntitySpec(aspectSpecs, entityAnnotation, entitySnapshotRecordSchema,
          (TyperefDataSchema) aspectArraySchema.getItems());

      validateEntitySpec(entitySpec);

      return entitySpec;
    }

    failValidation(String.format("Could not build entity spec for entity with name %s. Missing @%s annotation.",
        entitySnapshotRecordSchema.getName(), EntityAnnotation.ANNOTATION_NAME));
    return null;
  }

  public EntitySpec buildEntitySpec(@Nonnull final DataSchema entitySnapshotSchema,
      @Nonnull final List<AspectSpec> aspectSpecs) {

    // 0. Validate the Snapshot definition
    final RecordDataSchema entitySnapshotRecordSchema = validateSnapshot(entitySnapshotSchema);

    // 1. Parse information about the entity from the "entity" annotation.
    final Object entityAnnotationObj = entitySnapshotRecordSchema.getProperties().get(EntityAnnotation.ANNOTATION_NAME);

    if (entityAnnotationObj != null) {

      EntityAnnotation entityAnnotation =
          EntityAnnotation.fromSchemaProperty(entityAnnotationObj, entitySnapshotRecordSchema.getFullName());

      final EntitySpec entitySpec = new DefaultEntitySpec(aspectSpecs, entityAnnotation, entitySnapshotRecordSchema);

      validateEntitySpec(entitySpec);

      return entitySpec;
    }

    failValidation(String.format("Could not build entity spec for entity with name %s. Missing @%s annotation.",
        entitySnapshotRecordSchema.getName(), EntityAnnotation.ANNOTATION_NAME));
    return null;
  }

  public AspectSpec buildAspectSpec(@Nonnull final DataSchema aspectDataSchema) {

    final RecordDataSchema aspectRecordSchema = validateAspect(aspectDataSchema);

    final Object aspectAnnotationObj = aspectRecordSchema.getProperties().get(AspectAnnotation.ANNOTATION_NAME);

    if (aspectAnnotationObj != null) {

      final AspectAnnotation aspectAnnotation =
          AspectAnnotation.fromSchemaProperty(aspectAnnotationObj, aspectRecordSchema.getFullName());

      if (AnnotationExtractionMode.IGNORE_ASPECT_FIELDS.equals(_extractionMode)) {
        // Short Circuit.
        return new AspectSpec(aspectAnnotation, Collections.emptyList(), Collections.emptyList(),
            Collections.emptyList(), Collections.emptyList(), aspectRecordSchema);
      }

      final SchemaAnnotationProcessor.SchemaAnnotationProcessResult processedSearchResult =
          SchemaAnnotationProcessor.process(Collections.singletonList(_searchHandler), aspectRecordSchema,
              new SchemaAnnotationProcessor.AnnotationProcessOption());

      // Extract Searchable Field Specs
      final SearchableFieldSpecExtractor searchableFieldSpecExtractor = new SearchableFieldSpecExtractor();
      final DataSchemaRichContextTraverser searchableFieldSpecTraverser =
          new DataSchemaRichContextTraverser(searchableFieldSpecExtractor);
      searchableFieldSpecTraverser.traverse(processedSearchResult.getResultSchema());

      final SchemaAnnotationProcessor.SchemaAnnotationProcessResult processedRelationshipResult =
          SchemaAnnotationProcessor.process(Collections.singletonList(_relationshipHandler), aspectRecordSchema,
              new SchemaAnnotationProcessor.AnnotationProcessOption());

      // Extract Relationship Field Specs
      final RelationshipFieldSpecExtractor relationshipFieldSpecExtractor = new RelationshipFieldSpecExtractor();
      final DataSchemaRichContextTraverser relationshipFieldSpecTraverser =
          new DataSchemaRichContextTraverser(relationshipFieldSpecExtractor);
      relationshipFieldSpecTraverser.traverse(processedRelationshipResult.getResultSchema());

      // Capture the list of entity names from relationships extracted.
      _relationshipFieldSpecs.addAll(relationshipFieldSpecExtractor.getSpecs());

      final SchemaAnnotationProcessor.SchemaAnnotationProcessResult processedTimeseriesFieldResult =
          SchemaAnnotationProcessor.process(
              ImmutableList.of(_timeseriesFiledAnnotationHandler, _timeseriesFieldCollectionHandler),
              aspectRecordSchema, new SchemaAnnotationProcessor.AnnotationProcessOption());

      // Extract TimeseriesField/ TimeseriesFieldCollection Specs
      final TimeseriesFieldSpecExtractor timeseriesFieldSpecExtractor = new TimeseriesFieldSpecExtractor();
      final DataSchemaRichContextTraverser timeseriesFieldSpecTraverser =
          new DataSchemaRichContextTraverser(timeseriesFieldSpecExtractor);
      timeseriesFieldSpecTraverser.traverse(processedTimeseriesFieldResult.getResultSchema());

      return new AspectSpec(aspectAnnotation, searchableFieldSpecExtractor.getSpecs(),
          relationshipFieldSpecExtractor.getSpecs(), timeseriesFieldSpecExtractor.getTimeseriesFieldSpecs(),
          timeseriesFieldSpecExtractor.getTimeseriesFieldCollectionSpecs(), aspectRecordSchema);
    }

    failValidation(String.format("Could not build aspect spec for aspect with name %s. Missing @Aspect annotation.",
        aspectRecordSchema.getName()));

    return null;
  }

  private void validateEntitySpec(EntitySpec entitySpec) {

    if (entitySpec.getKeyAspectSpec() == null) {
      failValidation(
          String.format("Did not find required Key Aspect with name %s in aspects for Entity %s in list of aspects.",
              entitySpec.getKeyAspectName(), entitySpec.getName()));
    }

    validateKeyAspect(entitySpec.getKeyAspectSpec());

    // Validate aspect specs
    Set<String> aspectNames = new HashSet<>();
    for (final AspectSpec aspectSpec : entitySpec.getAspectSpecs()) {
      validateAspect(aspectSpec);
      if (aspectNames.contains(aspectSpec.getName())) {
        failValidation(String.format(
            "Could not build entity spec for entity with name %s." + " Found multiple Aspects with the same name %s",
            entitySpec.getName(), aspectSpec.getName()));
      }
      aspectNames.add(aspectSpec.getName());
    }

    // Validate entity name
    if (_entityNames.contains(entitySpec.getName().toLowerCase())) {
      // Duplicate entity found.
      failValidation(String.format("Could not build entity spec for entity with name %s."
          + " Found multiple Entity Snapshots with the same name.", entitySpec.getName()));
    }

    _entityNames.add(entitySpec.getName().toLowerCase());
  }

  private void validateAspect(final AspectSpec aspectSpec) {
    if (aspectSpec.isTimeseries()) {
      if (aspectSpec.getPegasusSchema().contains(TIMESTAMP_FIELD_NAME)) {
        DataSchema timestamp = aspectSpec.getPegasusSchema().getField(TIMESTAMP_FIELD_NAME).getType();
        if (timestamp.getType() == DataSchema.Type.LONG) {
          return;
        }
      }
      failValidation(String.format("Aspect %s is of type timeseries but does not include TimeseriesAspectBase",
          aspectSpec.getName()));
    }
  }

  private RecordDataSchema validateSnapshot(@Nonnull final DataSchema entitySnapshotSchema) {
    // 0. Validate that schema is a Record
    if (entitySnapshotSchema.getType() != DataSchema.Type.RECORD) {
      failValidation(
          String.format("Failed to validate entity snapshot schema of type %s. Schema must be of record type.",
              entitySnapshotSchema.getType().toString()));
    }

    final RecordDataSchema entitySnapshotRecordSchema = (RecordDataSchema) entitySnapshotSchema;

    // 1. Validate Urn field
    if (entitySnapshotRecordSchema.getField(URN_FIELD_NAME) == null
        || entitySnapshotRecordSchema.getField(URN_FIELD_NAME).getType().getDereferencedType()
        != DataSchema.Type.STRING) {
      failValidation(String.format("Failed to validate entity snapshot schema with name %s. Invalid urn field.",
          entitySnapshotRecordSchema.getName()));
    }

    // 2. Validate Aspect Array
    if (entitySnapshotRecordSchema.getField(ASPECTS_FIELD_NAME) == null
        || entitySnapshotRecordSchema.getField(ASPECTS_FIELD_NAME).getType().getDereferencedType()
        != DataSchema.Type.ARRAY) {

      failValidation(String.format(
          "Failed to validate entity snapshot schema with name %s. Invalid aspects field found. "
              + "'aspects' should be an array of union type.", entitySnapshotRecordSchema.getName()));
    }

    // 3. Validate Aspect Union
    final ArrayDataSchema aspectArray =
        (ArrayDataSchema) entitySnapshotRecordSchema.getField(ASPECTS_FIELD_NAME).getType().getDereferencedDataSchema();
    if (aspectArray.getItems().getType() != DataSchema.Type.TYPEREF
        || aspectArray.getItems().getDereferencedType() != DataSchema.Type.UNION) {

      failValidation(String.format(
          "Failed to validate entity snapshot schema with name %s. Invalid aspects field field. "
              + "'aspects' should be an array of union type.", entitySnapshotRecordSchema.getName()));
    }

    return entitySnapshotRecordSchema;
  }

  private RecordDataSchema validateAspect(@Nonnull final DataSchema aspectSchema) {
    // Validate that schema is a Record
    if (aspectSchema.getType() != DataSchema.Type.RECORD) {
      failValidation(String.format("Failed to validate aspect schema of type %s. Schema must be of record type.",
          aspectSchema.getType().toString()));
    }
    return (RecordDataSchema) aspectSchema;
  }

  private void validateKeyAspect(@Nonnull final AspectSpec keyAspect) {
    // Validate that schema is a Record
    RecordDataSchema schema = keyAspect.getPegasusSchema();
    // Validate that each field is a string or enum.
    for (RecordDataSchema.Field field : schema.getFields()) {
      if (!DataSchema.Type.STRING.equals(field.getType().getDereferencedType()) && !DataSchema.Type.ENUM.equals(
          field.getType().getDereferencedType())) {
        failValidation(String.format("Failed to validate key aspect nameed %s. Key "
                + "aspects must only contain fields of STRING or ENUM type. Found %s.", keyAspect.getName(),
            field.getType().toString()));
      }
    }
  }

  private void failValidation(@Nonnull final String message) {
    throw new ModelValidationException(message);
  }

  public enum AnnotationExtractionMode {
    /**
     * Extract all annotations types, the default.
     */
    DEFAULT,
    /**
     * Skip annotations on aspect record fields, only
     * parse entity + aspect annotations.
     */
    IGNORE_ASPECT_FIELDS
  }
}
